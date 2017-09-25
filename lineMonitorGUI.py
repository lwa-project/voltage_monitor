#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import pytz
import time
import getopt
import socket
import thread

import pylab

from collections import deque

import re
from datetime import datetime, timedelta

dataRE = re.compile(r'^\[(?P<date>.*)\] (?P<type>[A-Z0-9]*): (?P<data>.*)$')


def usage(exitCode=None):
	print """lineMonitorGUI.py - Read data from a monitorLine.py line voltage
monitoring server and plot the voltage.

Usage: lineMonitorGUI.py [OPTIONS]

Options:
-h, --help                  Display this help information
-a, --address               Mulitcast address to connect to (default = 224.168.2.10)
-p, --port                  Multicast port to connect on (default = 7165)
"""
	
	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseOptions(args):
	config = {}
	config['addr'] = "224.168.2.10"
	config['port'] = 7165

	try:
		opts, args = getopt.getopt(args, "ha:p:", ["help", "address=", "port="])
	except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
	
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		elif opt in ('-a', '--address'):
			config['addr'] = str(value)
		elif opt in ('-p', '--port'):
			config['port'] = int(value)
		else:
			assert False
	
	# Add in arguments
	config['args'] = args

	# Return configuration
	return config


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
	
	# Setup the storage array
	times120 = deque([], 300)
	volts120 = deque([], 300)
	times240 = deque([], 300)
	volts240 = deque([], 300)
	
	pylab.ion()
	
	# Main reading loop
	try:
		while True:
			try:
				data, addr = sock.recvfrom(1024)

				# RegEx matching for message date, type, and content
				mtch = dataRE.match(data)
				t = datetime.strptime(mtch.group('date'), "%Y-%m-%d %H:%M:%S.%f")
				
				# Deal with the data
				if mtch.group('type') == '120VAC':
					times120.append( t )
					volts120.append( float(mtch.group('data')) )
					
				elif mtch.group('type') == '240VAC':
					times240.append( t )
					volts240.append( float(mtch.group('data')) )
					
				pylab.clf()
				pylab.plot( times120, volts120, linestyle='', marker='x', color='blue')
				pylab.plot( times240, volts240, linestyle='', marker='+', color='green')
				pylab.xlabel('Time [UTC]')
				pylab.ylabel('Volts AC')
				r = pylab.xlim()
				pylab.hlines(120*1.0, *r, linestyle=':', color='black')
				pylab.hlines(120*0.9, *r, linestyle='--', color='orange')
				pylab.hlines(120*1.1, *r, linestyle='--', color='orange')
				pylab.hlines(240*1.0, *r, linestyle=':', color='black')
				pylab.hlines(240*0.9, *r, linestyle='-.', color='red')
				pylab.hlines(240*1.1, *r, linestyle='-.', color='red')
				pylab.draw()
				
			except socket.error, e:
				pass
				
	except KeyboardInterrupt:
		sock.close()
		print ''
		
	pylab.ioff()


if __name__ == "__main__":
	config = parseOptions(sys.argv[1:])
	
	DLVM(mcastAddr=config['addr'], mcastPort=config['port'])
	