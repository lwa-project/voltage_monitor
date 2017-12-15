#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Command line interface to the line voltage monitoring data served up by 
lineMonitor.py

$Rev$
$LastChangedBy$
$LastChangedDate$
"""

import os
import sys
import pytz
import time
import getopt
import socket
import thread
from socket import gethostname

import smtplib
from email.mime.text import MIMEText

import re
from datetime import datetime, timedelta

dataRE = re.compile(r'^\[(?P<date>.*)\] (?P<type>[A-Z0-9]*): (?P<data>.*)$')

# Site
SITE = gethostname().split('-', 1)[0]

# E-mail Users
TO = ['lwa1ops@phys.unm.edu',]

# SMTP user and password
#if SITE == 'lwa1':
FROM = 'lwa.station.1@gmail.com'
PASS = '1mJy4LWA'
#elif SITE == 'lwasv':
#	FROM = 'lwa.station.sv@gmail.com'
#	PASS = '1mJy4LWA'
#else:
#	raise RuntimeError("Unknown site '%s'" % SITE)

# State directory
STATE_DIR = '/home/jdowell/.shl-state/'
if not os.path.exists(STATE_DIR):
	os.mkdir(STATE_DIR)
else:
	if not os.path.isdir(STATE_DIR):
		raise RuntimeError("'%s' is not a directory" % STATE_DIR)

# Timezones
UTC = pytz.utc
MST = pytz.timezone('US/Mountain')


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
	print """sendPowerEmail.py - Read data from a monitorLine.py line voltage
monitoring server and send out an e-mail if there are problems.

Usage: sendPowerEmail.py [OPTIONS]

Options:
-h, --help                  Display this help information
-a, --address               Mulitcast address to connect to (default = 224.168.2.10)
-p, --port                  Multicast port to connect on (default = 7165)
-i, --pid-file              File to write the current PID to
"""

	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseOptions(args):
	config = {}
	config['pidFile'] = None
	config['addr'] = "224.168.2.10"
	config['port'] = 7165

	try:
		opts, args = getopt.getopt(args, "ha:p:i:", ["help", "address=", "port=", "pid-file="])
	except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
	
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		elif opt in ('-i', '--pid-file'):
			config['pidFile'] = str(value)
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


def sendEmail(subject, message, debug=False):
	"""
	Send an e-mail via the LWA1 operator list
	"""
	
	msg = MIMEText(message)
	msg['Subject'] = subject
	msg['From'] = FROM
	msg['To'] = ','.join(TO)
	
	try:
		server = smtplib.SMTP('smtp.gmail.com', 587)
		if debug:
			server.set_debuglevel(1)
		server.starttls()
		server.login(FROM, PASS)
		server.sendmail(FROM, TO, msg.as_string())
		server.close()
		return True
	except Exception, e:
		print str(e)
		return False

def sendFlicker(flicker120, flicker240):
	"""
	Send a `power flicker` message.
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
	
	# Setup the flicker trackers
	flicker120 = False
	flicker240 = False
	
	# Setup the outage trackers
	outage120 = False
	outage240 = False
	
	# Main reading loop
	try:
		while True:
			try:
				tNow = datetime.utcnow()
				data, addr = sock.recvfrom(1024)
				
				# RegEx matching for message date, type, and content
				mtch = dataRE.match(data)
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
					if mtch.group('data').find('120V') != -1:
						flicker120 = False
						outage120 = False
					else:
						flicker240 = False
						outage240 = False
						
				if flicker120 or flicker240:
					try:
						age120 = tNow - flicker120
					except:
						age120 = timedelta(0)
					try:
						age240 = tNow - flicker240
					except:
						age240 = timedelta(0)
					if age120 > timedelta(seconds=2) or age240 > timedelta(seconds=2):
						thread.start_new_thread(sendFlicker, (flicker120, flicker240))
					
				elif outage120 or outage240:
					if not os.path.exists(os.path.join(STATE_DIR, 'inPowerFailure')):
						thread.start_new_thread(sendOutage, (outage120, outage240))
						
					# Touch the file to update the modification time.  This is used to track
					# when the warning condition is cleared.
					try:
						fh = open(os.path.join(STATE_DIR, 'inPowerFailure'), 'w')
						fh.write('%s\n' % t)
						fh.close()
					except Exception as e:
						print str(e)
						
				else:
					if os.path.exists(os.path.join(STATE_DIR, 'inPowerFailure')):
						# Check the age of the holding file to see if we have entered the "all-clear"
						age = time.time() - os.path.getmtime(os.path.join(STATE_DIR, 'inPowerFailure'))
						
						if age >= 5*60:
							thread.start_new_thread(sendClear, ())
							
							try:
								os.unlink(os.path.join(STATE_DIR, 'inPowerFailure'))
							except Exception as e:
								print str(e)
								
			except socket.error, e:
				pass
				
	except KeyboardInterrupt:
		sock.close()
		print ''


if __name__ == "__main__":
	daemonize('/dev/null','/tmp/spe-stdout','/tmp/spe-stderr')
	
	config = parseOptions(sys.argv[1:])
	
	# PID file
	if config['pidFile'] is not None:
		fh = open(config['pidFile'], 'w')
		fh.write("%i\n" % os.getpid())
		fh.close()
		
	DLVM(mcastAddr=config['addr'], mcastPort=config['port'])
