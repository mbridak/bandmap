#! /usr/bin/env python3

"""
This is an RBN spot bandmap list which filters the spotters by distance.
If you limit the RBN spotting stations to those closest to you, you can
limit the reported spots to those you can actually have a chance to hear.
It does no good to get WFD CW spots from Italy if you're in Texas...

Change the 'mygrid' variable to your own grid.
Change the 'maxspotterdistance' to some distance in miles.

I'm in SoCal so I set mine to 500 wich gets me about 8 regional spotters.
If your in South Dakota, you may have to expand your circle a bit.

An easy way to start, is check the RBN when you call CQ to see who spots You.
Find the furthest spotter, figure out how far away they are and make that your distance.

The 'showoutofband' variable if True, will show spots outside of the General band. If your an
Advanced or Extra make sure this is true. If you're a general like me, make it false.
No use in seeing spots you can respond to...
"""
# pylint: disable=global-statement

import logging
import argparse
import re
import time
import xmlrpc.client
from math import atan2, cos, radians, sin, sqrt
from threading import Lock, Thread

import requests

from rich.logging import RichHandler
from rich.traceback import install
from rich import print  # pylint: disable=redefined-builtin
from rich.console import Console

from bs4 import BeautifulSoup as bs

from bandmap.lib.database import DataBase
from bandmap.lib.telnetlib import Telnet


logging.basicConfig(
    level="CRITICAL",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)


install(show_locals=True)


parser = argparse.ArgumentParser(
    description="Pull RBN spots, filter spotters w/ in a certain distance."
)
parser.add_argument("-c", "--call", type=str, help="Your callsign")
parser.add_argument("-m", "--mygrid", type=str, help="Your gridsquare")
parser.add_argument(
    "-d",
    "--distance",
    type=int,
    help="Limit to radius in miles from you to spotter, default is: 500",
)
parser.add_argument(
    "-g",
    "--general",
    action="store_true",
    help="Limit spots to general portion of the band.",
)
parser.add_argument(
    "-a", "--age", type=int, help="Drop spots older than (age) seconds. Default is: 600"
)
parser.add_argument(
    "-r", "--rbn", type=str, help="RBN server. Default is: telnet.reversebeacon.net"
)
parser.add_argument(
    "-p", "--rbnport", type=int, help="RBN server port. Default is: 7000"
)
parser.add_argument(
    "-b",
    "--bands",
    nargs="+",
    type=str,
    help="Space separated list of bands to receive spots about. Default is: 160 80 40 20 15 10 6",
)
parser.add_argument(
    "-f", "--flrighost", type=str, help="Hostname/IP of flrig. Default is: localhost"
)
parser.add_argument("-P", "--flrigport", type=int, help="flrig port. Default is: 12345")
parser.add_argument(
    "-l", "--log", type=str, help="Log DB file to monitor. Default is: WFD.db"
)

args = parser.parse_args()

if args.call:
    MY_CALL = args.call
else:
    MY_CALL = "w1aw"

if args.mygrid:
    MY_GRID = args.mygrid.upper()
else:
    MY_GRID = "DM13AT"

if args.distance:
    MAX_SPOTTER_DISTANCE = args.distance
else:
    MAX_SPOTTER_DISTANCE = 500

if args.general:
    SHOW_OUT_OF_BAND = False
else:
    SHOW_OUT_OF_BAND = True

if args.age:
    SPOT_TO_OLD = args.age
else:
    SPOT_TO_OLD = 600  # 10 minutes

if args.rbn:
    RBN_SERVER = args.rbn
else:
    RBN_SERVER = "telnet.reversebeacon.net"

if args.rbnport:
    RBN_PORT = args.rbnport
else:
    RBN_PORT = 7000

if args.bands:
    LIMIT_BANDS = tuple(str(args.bands).split())
else:
    LIMIT_BANDS = ("80", "40", "20", "15", "10", "6")

if args.flrighost:
    FLRIG_HOST = args.flrighost
else:
    FLRIG_HOST = "localhost"

if args.flrigport:
    FLRIG_PORT = args.flrigport
else:
    FLRIG_PORT = 12345

if args.log:
    LOG_DB_NAME = args.log
else:
    LOG_DB_NAME = "WFD.db"

server = xmlrpc.client.ServerProxy(f"http://{FLRIG_HOST}:{FLRIG_PORT}")

lock = Lock()
console = Console(width=38)
localspotters = []
THE_VFO = 0.0
OLD_VFO = 0.0
CONTACTLIST = {}
RBN_PARSER = r"^DX de ([A-Z\d\-\/]*)-#:\s+([\d.]*)\s+([A-Z\d\-\/]*)\s+([A-Z\d]*)\s+(\d*) dB.*\s+(\d{4}Z)"  # pylint: disable=line-too-long
database = DataBase(LOG_DB_NAME)


def updatecontactlist():
    """
    Scans the loggers database and builds a callsign on band dictionary
    so the spots can be flagged red so you know you can bypass them on the bandmap.
    """
    global CONTACTLIST
    CONTACTLIST = {}
    result = database.get_contacts()
    for contact in result:
        band = contact.get("band")
        callsign = contact.get("callsign")

        if band in CONTACTLIST:
            CONTACTLIST[band].append(callsign)
        else:
            CONTACTLIST[band] = list()
            CONTACTLIST[band].append(callsign)


def alreadyworked(callsign, band):
    """
    Check if callsign has already been worked on band.
    """
    if str(band) in CONTACTLIST:
        return callsign in CONTACTLIST[str(band)]
    return False


def getvfo():
    """
    Get the freq from the active VFO in khz.
    """
    global THE_VFO
    while True:
        try:
            THE_VFO = float(server.rig.get_vfo()) / 1000
        except ValueError:
            THE_VFO = 0.0
        except TypeError:
            THE_VFO = 0.0
        time.sleep(0.25)


def comparevfo(freq):
    """
    Return the difference in khz between the VFO and the spot.
    Spots show up in Blue, Grey, Dark Grey, Black backgrounds depending on how far away you VFO is.
    """
    freq = float(freq)
    difference = 0.0
    if THE_VFO < freq:
        difference = freq - THE_VFO
    else:
        difference = THE_VFO - freq
    return difference


def gridtolatlon(maiden):
    """
    Convert a 2,4,6 or 8 character maidenhead gridsquare to a latitude longitude pair.
    """
    maiden = str(maiden).strip().upper()

    maidenhead_resolution = len(maiden)
    if not 8 >= maidenhead_resolution >= 2 and maidenhead_resolution % 2 == 0:
        return 0, 0

    lon = (ord(maiden[0]) - 65) * 20 - 180
    lat = (ord(maiden[1]) - 65) * 10 - 90

    if maidenhead_resolution >= 4:
        lon += (ord(maiden[2]) - 48) * 2
        lat += ord(maiden[3]) - 48

    if maidenhead_resolution >= 6:
        lon += (ord(maiden[4]) - 65) / 12 + 1 / 24
        lat += (ord(maiden[5]) - 65) / 24 + 1 / 48

    if maidenhead_resolution >= 8:
        lon += (ord(maiden[6])) * 5.0 / 600
        lat += (ord(maiden[7])) * 2.5 / 600

    return lat, lon


def getband(freq):
    """
    Convert a (float) frequency into a (string) band.
    Returns a (string) band.
    Returns a "0" if frequency is out of band.
    """
    try:
        frequency = int(float(freq)) * 1000
    except ValueError:
        frequency = 0.0
    except TypeError:
        frequency = 0.0
    if frequency > 1800000 and frequency < 2000000:
        return "160"
    if frequency > 3500000 and frequency < 4000000:
        return "80"
    if frequency > 5330000 and frequency < 5406000:
        return "60"
    if frequency > 7000000 and frequency < 7300000:
        return "40"
    if frequency > 10100000 and frequency < 10150000:
        return "30"
    if frequency > 14000000 and frequency < 14350000:
        return "20"
    if frequency > 18068000 and frequency < 18168000:
        return "17"
    if frequency > 21000000 and frequency < 21450000:
        return "15"
    if frequency > 24890000 and frequency < 24990000:
        return "12"
    if frequency > 28000000 and frequency < 29700000:
        return "10"
    if frequency > 50000000 and frequency < 54000000:
        return "6"
    if frequency > 144000000 and frequency < 148000000:
        return "2"

    return "0"


def calc_distance(grid1, grid2):
    """
    Takes two maidenhead gridsquares and returns the distance between the two in kilometers.
    """
    earth_radius = 6371
    lat1, long1 = gridtolatlon(grid1)
    lat2, long2 = gridtolatlon(grid2)

    d_lat = radians(lat2) - radians(lat1)
    d_long = radians(long2) - radians(long1)

    r_lat1 = radians(lat1)
    # r_long1 = radians(long1)
    r_lat2 = radians(lat2)
    # r_long2 = radians(long2)

    the_a = sin(d_lat / 2) * sin(d_lat / 2) + cos(r_lat1) * cos(r_lat2) * sin(
        d_long / 2
    ) * sin(d_long / 2)
    the_c = 2 * atan2(sqrt(the_a), sqrt(1 - the_a))
    the_distance = earth_radius * the_c  # distance in km

    return the_distance


def inband(freq):
    """
    Returns True if the frequency is within the General portion of the band.
    """
    in_band = False
    if freq > 1800 and freq < 2000:
        in_band = True
    if freq > 3525 and freq < 3600:
        in_band = True
    if freq > 3800 and freq < 4000:
        in_band = True
    if freq > 7025 and freq < 7125:
        in_band = True
    if freq > 7175 and freq < 7300:
        in_band = True
    if freq > 10100 and freq < 10150:
        in_band = True
    if freq > 14025 and freq < 14150:
        in_band = True
    if freq > 14225 and freq < 14350:
        in_band = True
    if freq > 18068 and freq < 18168:
        in_band = True
    if freq > 21025 and freq < 21200:
        in_band = True
    if freq > 21275 and freq < 21450:
        in_band = True
    if freq > 24890 and freq < 24990:
        in_band = True
    if freq > 28000 and freq < 29700:
        in_band = True
    if freq > 50000 and freq < 54000:
        in_band = True
    return in_band


def showspots(the_lock):
    """
    Show spot list, sorted by frequency.
    Prune the list if it's longer than the window by removing the oldest spots.
    If tracking your VFO highlight those spots in/near your bandpass.
    Mark those already worked in red.
    """
    while True:
        updatecontactlist()
        console.clear()
        console.rule(f"[bold red]Spots VFO: {THE_VFO}")
        with the_lock:
            result = DataBase.getspots()
        displayed = 2
        for spot in result:
            _, callsign, date_time, frequency, band, delta = spot
            displayed += 1
            if displayed > console.height:
                with the_lock:
                    DataBase.prune_oldest_spot()
            else:
                if inband(frequency):
                    style = ""
                else:
                    style = ""  # if in extra/advanced band
                if comparevfo(frequency) < 0.8:
                    style = "bold on color(237)"
                if comparevfo(frequency) < 0.5:
                    style = "bold on color(240)"
                if comparevfo(frequency) < 0.2:
                    style = "bold on blue"
                if alreadyworked(callsign, band):
                    style = "bold on color(88)"
                console.print(
                    (
                        f"{callsign.ljust(11)} {str(frequency).rjust(8)} "
                        f"{str(band).rjust(3)}M {date_time.split()[1]} {delta}"
                    ),
                    style=style,
                    overflow="ellipsis",
                )
        time.sleep(1)


def getrbn(the_lock):
    """Thread to get RBN spots"""
    with Telnet(RBN_SERVER, RBN_PORT) as tn_connection:
        while True:
            stream = tn_connection.read_until(b"\r\n", timeout=1.0)
            if stream == b"":
                continue
            stream = stream.decode()
            if "Please enter your call:" in stream:
                tn_connection.write(f"{MY_CALL}\r\n".encode("ascii"))
                continue
            data = stream.split("\r\n")
            for entry in data:
                if not entry:
                    continue
                parsed = list(re.findall(RBN_PARSER, entry.strip()))
                if not parsed or len(parsed[0]) < 6:
                    continue
                spotter = parsed[0][0]
                mode = parsed[0][3]
                if not mode == "CW":
                    continue
                if not spotter in localspotters:
                    continue
                freq = float(parsed[0][1])
                band = getband(freq)
                callsign = parsed[0][2]
                if not inband(float(freq)) and SHOW_OUT_OF_BAND is False:
                    continue
                if band in LIMIT_BANDS:
                    with the_lock:
                        DataBase.add_spot(callsign, freq, band, SPOT_TO_OLD)


def run():
    """Main Entry"""
    console.clear()
    updatecontactlist()
    console.rule("[bold red]Finding Spotters")
    page = requests.get(
        "http://reversebeacon.net/cont_includes/status.php?t=skt", timeout=10.0
    )
    soup = bs(page.text, "lxml")
    rows = soup.find_all("tr", {"class": "online"})
    for row in rows:
        datum = row.find_all("td")
        spotter = datum[0].a.contents[0].strip()
        # bands = datum[1].contents[0].strip()
        grid = datum[2].contents[0]
        distance = calc_distance(grid, MY_GRID) / 1.609
        if distance < MAX_SPOTTER_DISTANCE:
            localspotters.append(spotter)

    print(f"Spotters with in {MAX_SPOTTER_DISTANCE} mi:")
    print(f"{localspotters}")
    time.sleep(1)
    DataBase.setup_spots_db(SPOT_TO_OLD)

    # Threading Oh my!
    thread_1 = Thread(target=getrbn, args=(lock,))
    thread_1.daemon = True
    thread_2 = Thread(target=showspots, args=(lock,))
    thread_2.daemon = True
    thread_3 = Thread(target=getvfo)
    thread_3.daemon = True

    thread_1.start()
    thread_2.start()
    thread_3.start()

    thread_1.join()
    thread_2.join()
    thread_3.join()
