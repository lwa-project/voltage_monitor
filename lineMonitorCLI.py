#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import pytz
import time
import socket
import thread
import argparse

from collections import deque

import re
from datetime import datetime, timedelta

dataRE = re.compile(r'^\[(?P<date>.*)\] (?P<type>[A-Z0-9]*): (?P<data>.*)$')


def DLVM(mcastAddr="224.168.2.10", mcastPort=7165):
    """
    Function responsible for reading the UDP multi-cast packets and printing them
    to the screen.
    """
    
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
    sock.setblocking(1)
    
    # Setup the state variable
    state = {'t120':None, 'v120':None, 't240':None, 'v240':None}
    
    # Main reading loop
    try:
        print("%19s  |  %9s  |  %19s  |  %9s" % ('Time 120', 'Volts 120', 'Time 240', 'Volts 240'))
        print("-"*(19*2 + 5*2 + 4*2 + 3 + 2*6))
        while True:
            try:
                tNow = datetime.utcnow()
                data, addr = sock.recvfrom(1024)

                # RegEx matching for message date, type, and content
                mtch = dataRE.match(data)
                t = datetime.strptime(mtch.group('date'), "%Y-%m-%d %H:%M:%S.%f")
                
                # Deal with the data
                if mtch.group('type') == '120VAC':
                    state['t120'] = t
                    state['v120'] = float(mtch.group('data'))
                    
                elif mtch.group('type') == '240VAC':
                    state['t240'] = t
                    state['v240'] = float(mtch.group('data'))
                    
                else:
                    print('NOTICE: %s - %s' % (mtch.group('type'), mtch.group('data')))
                    continue
                    
                # Flush out stale values
                if state['t120'] is not None:
                    if tNow-state['t120'] > timedelta(seconds=10):
                            state['t120'] = None
                            state['v120'] = None
                if state['t240'] is not None:
                    if tNow-state['t240'] > timedelta(seconds=10):
                            state['t240'] = None
                            state['v240'] = None
                            
                # Print out valid values
                t120 = state['t120'].strftime('%Y/%m/%d %H:%M:%S') if state['t120'] is not None else '---'
                v120 = '%5.1f' % state['v120'] if state['t120'] is not None else '---'
                t240 = state['t240'].strftime('%Y/%m/%d %H:%M:%S') if state['t240'] is not None else '---'
                v240 = '%5.1f' % state['v240'] if state['t240'] is not None else '---'
                print("%19s  |  %5s VAC  |  %19s  |  %5s VAC" % (t120, v120, t240, v240))
                
            except socket.error as e:
                pass
                
    except KeyboardInterrupt:
        sock.close()
        print('')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='read data from a monitorLine.py line voltage monitoring server and print the voltage',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
            )
    parser.add_argument('-a', '--address', type=str, default='224.168.2.10',
                        help='mulitcast address to connect to')
    parser.add_argument('-p', '--port', type=int, default=7165,
                        help='multicast port to connect on')
    args = parser.parse_args()
    
    DLVM(mcastAddr=args.address, mcastPort=args.port)
    