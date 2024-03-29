#!/usr/bin/env python3

"""
Command line interface to the line voltage monitoring data served up by 
lineMonitor.py
"""

import os
import re
import sys
import pytz
import time
import uuid
import socket
import argparse
import threading
import subprocess
from socket import gethostname

import smtplib
from email.mime.text import MIMEText

import re
from datetime import datetime, timedelta

from lwa_auth import STORE as LWA_AUTH_STORE

dataRE = re.compile(r'^\[(?P<date>.*)\] (?P<type>[A-Z0-9]*): (?P<data>.*)$')

# Site
SITE = gethostname().split('-', 1)[0]

# E-mail Users
TO = ['lwa1ops-l@list.unm.edu',]

# SMTP user and password
store_entry = LWA_AUTH_STORE.get('email')
FROM = store_entry.username
PASS = store_entry.password
ESRV = store_entry.url


# State directory
STATE_DIR = os.path.join(os.path.dirname(__file__), '.shl-state')
if not os.path.exists(STATE_DIR):
    os.mkdir(STATE_DIR)
else:
    if not os.path.isdir(STATE_DIR):
        raise RuntimeError("'%s' is not a directory" % STATE_DIR)


# Timezones
UTC = pytz.utc
MST = pytz.timezone('US/Mountain')


def get_uptime():
    """
    Determine and return the current uptime in minutes.
    """
    
    # Create a regular expresion to help us parse the uptime command
    upre = re.compile('up ((?P<days>\d+) day(s)?,)?\s*((?P<hours>\d+)\:)?(?P<minutes>\d+)( min(ute(s)?)?)?,')
    
    # Run the command and see if we have something that looks right
    output = subprocess.check_output(['uptime'])
    try:
        output = output.decode('ascii', errors='backslashreplace')
    except AttributeError:
        pass
    mtch = upre.search(output)
    if mtch is None:
        raise RuntimeError("Could not determine the current uptime")
    
    # Convert the uptime to minutes
    uptime = 0
    try:
        uptime += int(mtch.group('days'), 10)*24*60
    except (TypeError, ValueError):
        pass
    try:
        uptime += int(mtch.group('hours'), 10)*60
    except (TypeError, ValueError):
        pass
    try:
        uptime += int(mtch.group('minutes'), 10)
    except (TypeError, ValueError):
        pass
        
    # Done
    return uptime


def sendEmail(subject, message, debug=False):
    """
    Send an e-mail via the LWA1 operator list
    """
    
    message = "%s\n\nEmail ID: %s" % (message, str(uuid.uuid4()))
    
    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = FROM
    msg['To'] = ','.join(TO)
    msg.add_header('reply-to', TO[0])
    
    try:
        server = smtplib.SMTP(ESRV, 587)
        if debug:
            server.set_debuglevel(1)
        server.starttls()
        server.login(FROM, PASS)
        server.sendmail(FROM, TO, msg.as_string())
        server.close()
        return True
    except Exception as e:
        print("ERROR: failed to send message - %s" % str(e))
        return False

def sendFlicker(flicker120, flicker240):
    """
    Send a `power flicker` message.
    """
    
    tNow = datetime.utcnow()
    tNow = UTC.localize(tNow)
    tNow = tNow.astimezone(MST)
    
    tNow = tNow.strftime("%B %d, %Y %H:%M:%S %Z")
    
    if flicker120 and flicker240:
        lines = '120VAC and 240VAC lines'
    elif flicker120 and not flicker240:
        lines = '120VAC line'
    elif not flicker120 and flicker240:
        lines = '240VAC line'
        
    subject = '%s - Power Flicker' % (SITE.upper(),)
    message = """At %s a power flicker was detected on the %s.""" % (tNow, lines)
    
    return sendEmail(subject, message)


def sendOutage(outage120, outage240):
    """
    Send a `power outage` message.
    """
    
    tNow = datetime.utcnow()
    tNow = UTC.localize(tNow)
    tNow = tNow.astimezone(MST)
    
    tNow = tNow.strftime("%B %d, %Y %H:%M:%S %Z")
    
    if outage120 and outage240:
        lines = '120VAC and 240VAC lines'
    elif outage120 and not outage240:
        lines = '120VAC line'
    elif not outage120 and outage240:
        lines = '240VAC line'
        
    subject = '%s - Power Outage' % (SITE.upper(),)
    message = """At %s a power outage was detected on the %s.""" % (tNow, lines)
    
    return sendEmail(subject, message)


def sendClear():
    """
    Send an "all clear" e-mail.
    """
    
    tNow = datetime.utcnow()
    tNow = UTC.localize(tNow)
    tNow = tNow.astimezone(MST)
    
    tNow = tNow.strftime("%B %d, %Y %H:%M:%S %Z")
    
    subject = '%s - Power Outage - Cleared' % (SITE.upper(),)
    message = "At %s all voltage monitoring points are normal." % tNow
    
    return sendEmail(subject, message)


def _connect(mcastAddr, mcastPort, sock=None, timeout=60):
    if sock is not None:
        sock.close()
        
    #create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    #allow multiple sockets to use the same PORT number
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    #Bind to the port that we know will receive multicast data
    sock.bind(("0.0.0.0", mcastPort))
    #tell the kernel that we are a multicast socket
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
    #Tell the kernel that we want to add ourselves to a multicast group
    #The address for the multicast group is the third param
    status = sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(mcastAddr) + socket.inet_aton("0.0.0.0"))
    # Set the timeout
    sock.settimeout(timeout)
    
    return sock


def DLVM(mcastAddr="224.168.2.10", mcastPort=7165):
    """
    Function responsible for reading the UDP multi-cast packets and printing them
    to the screen.
    """
    
    #create a UDP socket
    sock = _connect(mcastAddr, mcastPort)
    
    # Setup the flicker trackers
    flicker120 = False
    flicker240 = False
    lastFlicker = 0.0
    
    # Setup the outage trackers
    outage120 = False
    outage240 = False
    
    # Main reading loop
    try:
        while True:
            try:
                tNow = datetime.utcnow()
                try:
                    data, addr = sock.recvfrom(1024)
                except socket.timeout:
                    print('Timeout on socket, re-trying...')
                    sock = _connect(mcastAddr, mcastPort, sock=sock)
                    continue
                    
                # RegEx matching for message date, type, and content
                try:
                    data = data.decode('ascii')
                except AttributeError:
                    pass
                mtch = dataRE.match(data)
                if mtch is None:
                    continue
                t = datetime.strptime(mtch.group('date'), "%Y-%m-%d %H:%M:%S.%f")
                
                # Look for FLICKER, OUTAGE, and CLEAR messages
                if mtch.group('type') == 'FLICKER':
                    if mtch.group('data').find('120V') != -1:
                        flicker120 = t
                    else:
                        flicker240 = t
                        
                elif mtch.group('type') == 'OUTAGE':
                    if mtch.group('data').find('120V') != -1:
                        flicker120 = False
                        outage120 = True
                    else:
                        flicker240 = False
                        outage240 = True
                        
                elif mtch.group('type') == 'CLEAR':
                    ## Only for outages now
                    if mtch.group('data').find('120V') != -1:
                        outage120 = False
                    else:
                        outage240 = False
                        
                # Age out old flicker events since they are, by definition, transient
                if flicker120:
                    if flicker120 < tNow - timedelta(seconds=10):
                        flicker120 = False
                if flicker240:
                    if flicker240 < tNow - timedelta(seconds=10):
                        flicker240 = False
                        
                # Event handling
                if flicker120 or flicker240:
                    if time.time() - lastFlicker >= 60:
                        ## Rate limit the flicker e-mails to only one per minute
                        op = threading.Thread(target=sendFlicker, args=(flicker120, flicker240))
                        op.start()
                        lastFlicker = time.time()
                        
                elif outage120 or outage240:
                    if not os.path.exists(os.path.join(STATE_DIR, 'inPowerFailure')):
                        op = threading.Thread(target=sendOutage, args=(outage120, outage240))
                        op.start()
                        
                    ## Touch the file to update the modification time.  This is used to track
                    ## power outages across reboots.
                    try:
                        fh = open(os.path.join(STATE_DIR, 'inPowerFailure'), 'w')
                        fh.write('%s\n' % t)
                        fh.close()
                    except Exception as e:
                        print("ERROR: cannot write state file - %s" % str(e))
                        
                else:
                    if os.path.exists(os.path.join(STATE_DIR, 'inPowerFailure')):
                        if get_uptime() >= 5:
                            ## Make sure that the machine has been up at least 5 minutes to
                            ## give shelter a chance to boot/start SHL-MCS as well.
                            op = threading.Thread(target=sendClear)
                            op.start()
                            
                            try:
                                os.unlink(os.path.join(STATE_DIR, 'inPowerFailure'))
                            except Exception as e:
                                print("ERROR: cannot remove state file - %s" % str(e))
                                
            except socket.error as e:
                pass
                
    except KeyboardInterrupt:
        sock.close()
        print('')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='read data from a monitorLine.py line voltage monitoring server and send out an e-mail if there are problems',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
            )
    parser.add_argument('-a', '--address', type=str, default='224.168.2.10',
                        help='mulitcast address to connect to')
    parser.add_argument('-p', '--port', type=int, default=7165,
                        help='multicast port to connect on')
    parser.add_argument('-i', '--pid-file', type=str,
                        help='file to write the current PID to')
    args = parser.parse_args()
    
    # PID file
    if args.pid_file is not None:
        fh = open(args.pid_file, 'w')
        fh.write("%i\n" % os.getpid())
        fh.close()
        
    DLVM(mcastAddr=args.address, mcastPort=args.port)
