#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
lineMonitor.py - Python script for interfacing with a TekPower TP4000ZC DMM
and logging the AC voltages out at the site.

$Rev$
$LastChangedBy$
$LastChangedDate$
"""

import os
import re
import sys
import time
import numpy
import serial
import socket
import getopt
import threading
from collections import deque
from datetime import datetime, timedelta

import logging
try:
	from logging.handlers import WatchedFileHandler
except ImportError:
	from logging import FileHandler as WatchedFileHandler

from tp4000zc import Dmm, DmmException


__version__ = '0.1'
__revision__ = '$Rev$'
__date__ = '$LastChangedDate$'


# Date formating string
dateFmt = "%Y-%m-%d %H:%M:%S.%f"


"""
This module is used to fork the current process into a daemon.
Almost none of this is necessary (or advisable) if your daemon
is being started by inetd. In that case, stdin, stdout and stderr are
all set up for you to refer to the network connection, and the fork()s
and session manipulation should not be done (to avoid confusing inetd).
Only the chdir() and umask() steps remain as useful.

From:
  http://code.activestate.com/recipes/66012-fork-a-daemon-process-on-unix/

References:
  UNIX Programming FAQ
    1.7 How do I get my program to act like a daemon?
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16

    Advanced Programming in the Unix Environment
      W. Richard Stevens, 1992, Addison-Wesley, ISBN 0-201-56317-7.
"""

def daemonize(stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
	"""
	This forks the current process into a daemon.
	The stdin, stdout, and stderr arguments are file names that
	will be opened and be used to replace the standard file descriptors
	in sys.stdin, sys.stdout, and sys.stderr.
	These arguments are optional and default to /dev/null.
	Note that stderr is opened unbuffered, so
	if it shares a file with stdout then interleaved output
	may not appear in the order that you expect.
	"""
	
	# Do first fork.
	try:
		pid = os.fork()
		if pid > 0:
			sys.exit(0) # Exit first parent.
	except OSError, e:
		sys.stderr.write("fork #1 failed: (%d) %s\n" % (e.errno, e.strerror))
		sys.exit(1)

	# Decouple from parent environment.
	os.chdir("/")
	os.umask(0)
	os.setsid()

	# Do second fork.
	try:
		pid = os.fork()
		if pid > 0:
			sys.exit(0) # Exit second parent.
	except OSError, e:
		sys.stderr.write("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
		sys.exit(1)

	# Now I am a daemon!

	# Redirect standard file descriptors.
	si = file(stdin, 'r')
	so = file(stdout, 'a+')
	se = file(stderr, 'a+', 0)
	os.dup2(si.fileno(), sys.stdin.fileno())
	os.dup2(so.fileno(), sys.stdout.fileno())
	os.dup2(se.fileno(), sys.stderr.fileno())


def usage(exitCode=None):
	print """lineMonitor.py - Read data from two TekPower TP4000ZC DMMS
and save the data to a log.

Usage: lineMonitor.py [OPTIONS]

Options:
-h, --help                  Display this help information
-c, --config-file           Path to configuration file
-p, --pid-file              File to write the current PID to
-l, --log-file              File to log operational status to
-d, --debug       Print debug messages as well as info and higher
"""

	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseOptions(args):
	config = {}
	config['configFile'] = 'monitoring.cfg'
	config['pidFilename'] = None
	config['logFilename'] = None
	config['debugMessages'] = False
	
	try:
		opts, args = getopt.getopt(args, "hc:p:l:d", ["help", "config-file=", "pid-file=", "log-file=", "debug"])
	except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
		
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		elif opt in ('-c', '--config-file'):
			config['configFile'] = str(value)
		elif opt in ('-p', '--pid-file'):
			config['pidFilename'] = str(value)
		elif opt in ('-l', '--log-file'):
			config['logFilename'] = str(value)
		elif opt in('-d', '--debug'):
			config['debugMessages'] = True
		else:
			assert False
			
	# Add in arguments
	config['args'] = args
	
	# Parse the configuration file
	cFile = parseConfigFile(config['configFile'])
	for k,v in cFile.iteritems():
		config[k] = v
		
	# Return configuration
	return config


def parseConfigFile(filename):
	"""
	Given the name of a configuration file, parse it and return a dictionary of
	the configuration parameters.  If the file doesn't exist or can't be opened,
	return the default values.
	"""
	
	config = {}
	
	config['SERIAL_PORT_120V'] = "/dev/ttyUSB0"
	config['SERIAL_PORT_240V'] = "/dev/ttyUSB1"
	
	config['MCAST_ADDR']  = "224.168.2.10"
	config['MCAST_PORT']  = 7165
	config['SEND_PORT']   = 7166
	
	config['VOLTAGE_LOGGING_DIR'] = '/lwa/LineMonitoring/logs/'
	
	# Defaults at 10% tolerance
	config['VOLTAGE_LOW_120V']  = 108.0
	config['VOLTAGE_HIGH_120V'] = 132.0
	config['VOLTAGE_LOW_240V']  = 216.0
	config['VOLTAGE_HIGH_240V'] = 264.0
	
	config['FLICKER_TIME'] = 0.0
	config['OUTAGE_TIME']  = 0.5
	
	try:
		fh = open(filename, 'r')
		for line in fh:
			line = line.replace('\n', '')
			if len(line) < 3:
				continue
			if line[0] == '#':
				continue
				
			keyword, value = line.split(None, 1)
			config[keyword] = value
	except Exception as err:
		print "WARNING:  could not parse configuration file '%s': %s" % (filename, str(err))
		
	return config


class DuplicateFilter(logging.Filter):
	last_log = None
	duplicate_count = 0
	
	def __init__(self, *args, **kwds):
		try:
			self.callback = kwds['callback']
			del kwds['callback']
		except KeyError:
			self.callback = None
			
		super(DuplicateFilter, self).__init__(*args, **kwds)
		
	
	def filter(self, record):
		# add other fields if you need more granular comparison, depends on your app
		current_log = (record.module, record.levelno, record.msg)
		if record.msg[:4] == '--- ':
			return True
			
		if current_log != self.last_log or self.duplicate_count >= 50:
			if self.duplicate_count > 0:
				if self.callback is not None:
					if current_log[1] == logging.CRITICAL:
						cbf = self.callback.critical
					elif current_log[1] == logging.ERROR:
						cbf = self.callback.error
					elif current_log[1] == logging.WARNING:
						cbf = self.callback.warning
					elif current_log[1] == logging.INFO:
						cbf = self.callback.info
					else:
						cbf = self.callback.debug
						
					cbf('--- %i identical messages suppressed', self.duplicate_count)
					
			self.last_log = current_log
			self.duplicate_count = 0
			return True
		else:
			self.duplicate_count += 1
			return False


class dataServer(object):
	def __init__(self, mcastAddr="224.168.2.9", mcastPort=7163, sendPort=7164):
		self.sendPort  = sendPort
		self.mcastAddr = mcastAddr
		self.mcastPort = mcastPort
		
		self.sock = None
		
	def start(self):
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		#The sender is bound on (0.0.0.0:7164)
		self.sock.bind(("0.0.0.0", self.sendPort))
		#Tell the kernel that we want to multicast and that the data is sent
		#to everyone (255 is the level of multicasting)
		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
		
	def stop(self):
		if self.sock is not None:
			self.sock.close()
			self.sock = None
		
	def send(self, data):
		if self.sock is not None:
			self.sock.sendto(data, (self.mcastAddr, self.mcastPort) )
        

def main(args):
	config = parseOptions(args)
	
	# PID file
	if config['pidFilename'] is not None:
		fh = open(config['pidFilename'], 'w')
		fh.write("%i\n" % os.getpid())
		fh.close()
		
	# Setup logging
	logger = logging.getLogger(__name__)
	logFormat = logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
	logFormat.converter = time.gmtime
	if config['logFilename'] is None:
		logHandler = logging.StreamHandler(sys.stdout)
	else:
		logHandler = WatchedFileHandler(config['logFilename'])
	logHandler.setFormatter(logFormat)
	logger.addHandler(logHandler)
	if config['debugMessages']:
		logger.setLevel(logging.DEBUG)
	else:
		logger.setLevel(logging.INFO)
	logger.addFilter(DuplicateFilter(callback=logger))
	
	# Report on who we are
	shortRevision = __revision__.split()[1]
	shortDate = ' '.join(__date__.split()[1:4])
	
	logger.info('Starting %s with PID %i', os.path.basename(__file__), os.getpid())
	logger.info('Version: %s', __version__)
	logger.info('Revision: %s', shortRevision)
	logger.info('Last Changed: %s',shortDate)
	logger.info('All dates and times are in UTC except where noted')
	
	# Connect to the meter(s)
	meter120, r120FH = None, sys.stdout
	if config['SERIAL_PORT_120V'] not in ('', 'none', 'None'):
		try:
			meter120 = Dmm(config['SERIAL_PORT_120V'])
			logger.info('Connected to 120V meter on %s', config['SERIAL_PORT_120V'])
		except (DmmException, serial.serialutil.SerialException) as e:
			meter120 = None
			logger.warning('Cannot connect to 120V meter: %s', str(e))
			
		r120FH = open(os.path.join(config['VOLTAGE_LOGGING_DIR'], 'voltage_120.log'), 'a')
	else:
		logger.warning('No 120V specified in the configuration file, skipping')
		
	meter240, r240FH = None, sys.stdout
	if config['SERIAL_PORT_240V'] not in ('', 'none', 'None'):
		try:
			meter240 = Dmm(config['SERIAL_PORT_240V'])
			logger.info('Connected to 240V meter on %s', config['SERIAL_PORT_240V'])
		except (DmmException, serial.serialutil.SerialException) as e:
			meter240 = None
			logger.warning('Cannot connect to 240V meter: %s', str(e))
			
		r240FH = open(os.path.join(config['VOLTAGE_LOGGING_DIR'], 'voltage_240.log'), 'a')
	else:
		logger.warning('No 240V specified in the configuration file, skipping')
		
	# Is there anything to do?
	if meter120 is None and meter240 is None:
		logger.fatal('No voltage meters found, aborting')
		logging.shutdown()
		sys.exit(1)
		
	# Start the data server
	server = dataServer(mcastAddr=config['MCAST_ADDR'], mcastPort=int(config['MCAST_PORT']), 
	                    sendPort=int(config['SEND_PORT']))
	server.start()
	
	# Set the voltage moving average variables
	voltage120 = []
	voltage240 = []
	
	# Setup the event detection variables
	state120 = {'start':None, 'stage0':False, 'stage1':False}
	state240 = {'start':None, 'stage0':False, 'stage1':False}
	
	# Read from the ports forever
	try:
		t0_120 = 0.0
		t0_240 = 0.0
		
		while True:
			## Set the (date)time
			tUTC = datetime.utcnow()
			
			## Read the data
			### 120V
			if meter120 is not None:
				try:
					data = meter120.read()
					t = time.time()
					u = '$\\Delta$' if data.delta else ''
					u += data.measurement
					u += ' %s' % data.ACDC if data.ACDC is not None else ''
					if u != 'volts AC':
						raise RuntimeError("Output is in '%s', not 'volts AC'" % u)
						
					v = data.numericVal
					r120FH.write("%.2f  %.1f\n" % (t, v))
					
					if v < config['VOLTAGE_LOW_120V'] or v > config['VOLTAGE_HIGH_120V']:
						logger.warning('120V is out of range at %.1f %s', v, u)
						if state120['start'] is None:
							state120['start'] = t
					else:
						if state120['start'] is not None:
							state120['start'] = None
							if state120['stage0']:
								logger.info('120V Flicker cleared')
								state120['stage0'] = False
								if not state120['state1']:
									server.send("[%s] CLEAR: 120V" % tUTC.strftime(dateFmt))
									
							if state120['stage1']:
								logger.info('120V Outage cleared')
								state120['stage1'] = False
								
								server.send("[%s] CLEAR: 120V" % tUTC.strftime(dateFmt))
								
					if state120['start'] is not None:
						age = t - state120['start']
						if age >= config['FLICKER_TIME']:
							if not state120['stage0']:
								logger.warning('120V has been out of tolerances for %.1f s', age)
								state120['stage0'] = True
								
								server.send("[%s] FLICKER: 120V" % tUTC.strftime(dateFmt))
								
							if age >= config['OUTAGE_TIME']:
								if not state120['stage1']:
									logger.error('120V has been out of tolerances for %.1f s', age)
									state120['stage1'] = True
									
									server.send("[%s] OUTAGE: 120V" % tUTC.strftime(dateFmt))
									
									
					if t-t0_120 > 10.0:
						logger.debug('120V meter is currently reading %.1f %s', v, u)
						r120FH.flush()
						t0_120 = t*1.0
						
					voltage120.append( v )
					if len(voltage120) == 4:
						voltage120 = sum(voltage120) / len(voltage120)
						server.send("[%s] 120VAC: %.2f" % (tUTC.strftime(dateFmt), voltage120))
						voltage120 = []
						
				except (TypeError, RuntimeError) as e:
					logger.warning('Error parsing 120V data: %s', str(e))
					
				except (DmmException, serial.serialutil.SerialException) as e:
					logger.warning('Error reading from 120V meter: %s', str(e))
					
			### 240V
			if meter240 is not None:
				try:
					data = meter240.read()
					t = time.time()
					u = '$\\Delta$' if data.delta else ''
					u += data.measurement
					u += ' %s' % data.ACDC if data.ACDC is not None else ''
					if u != 'volts AC':
						RuntimeError("Output is in '%s', not 'volts AC'" % u)
						
					v = data.numericVal
					r240FH.write("%.2f  %.1f\n" % (t, v))
					
					if v < config['VOLTAGE_LOW_240V'] or v > config['VOLTAGE_HIGH_240V']:
						logger.warning('240V is out of range at %.1f %s', v, u)
						if state240['start'] is None:
							state240['start'] = t
					else:
						if state240['start'] is not None:
							state240['start'] = None
							if state240['stage0']:
								logger.info('240V Flicker cleared')
								state240['stage0'] = False
								if not state240['state1']:
									server.send("[%s] CLEAR: 240V" % tUTC.strftime(dateFmt))
									
							if state240['stage1']:
								logger.info('240V Outage cleared')
								state240['stage1'] = False
								
								server.send("[%s] CLEAR: 240V" % tUTC.strftime(dateFmt))
								
					if state240['start'] is not None:
						age = t - state240['start']
						if age >= config['FLICKER_TIME']:
							if not state240['stage0']:
								logger.warning('240V has been out of tolerances for %.1f s', age)
								state240['stage0'] = True
								
								server.send("[%s] FLICKER: 240V" % tUTC.strftime(dateFmt))
								
							if age >= config['OUTAGE_TIME']:
								if not state240['stage1']:
									logger.error('240V has been out of tolerances for %.1f s', age)
									state240['stage1'] = True
									
									server.send("[%s] OUTAGE: 240V" % tUTC.strftime(dateFmt))
					
					if v < config['VOLTAGE_LOW_240V'] or v > config['VOLTAGE_HIGH_240V']:
						logger.warning('240V is out of range at %.1f %s', v, u)
						
					
					if t-t0_240 > 10.0:
						logger.debug('240V meter is currently reading %.1f %s', v, u)
						r240FH.flush()
						t0_240 = t*1.0
						
					voltage240.append( v )
					if len(voltage240) == 4:
						voltage240 = sum(voltage240) / len(voltage240)
						server.send("[%s] 240VAC: %.2f" % (tUTC.strftime(dateFmt), voltage240))
						voltage240 = []
						
				except (TypeError, RuntimeError) as e:
					logger.warning('Error parsing 240V data: %s', str(e))
					
				except (DmmException, serial.serialutil.SerialException) as e:
					logger.warning('Error reading from 240V meter: %s', str(e))
					
			## Sleep a bit
			time.sleep(0.2)
			
	except KeyboardInterrupt:
		logger.info("Interrupt received, shutting down")
		
		server.stop()
		
		if meter120 is not None:
			meter120.close()
		if meter240 is not None:
			meter240.close()
			
		try:
			r120FH.close()
		except:
			pass
		try:
			r240FH.close()
		except:
			pass
		
	# Exit
	logger.info('Finished')
	logging.shutdown()
	sys.exit(0)


if __name__ == "__main__":
	daemonize('/dev/null','/tmp/lm-stdout','/tmp/lm-stderr')
	main(sys.argv[1:])
	
