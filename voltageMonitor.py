#!/usr/bin/env python3

from __future__ import print_function

"""
lineMonitor.py - Python script for interfacing with a TekPower TP4000ZC DMM
and logging the AC voltages out at the site.
"""

import os
import re
import git
import sys
import json
import time
import numpy
import serial
import socket
import argparse
import threading
import json_minify
from collections import deque
from datetime import datetime, timedelta

import logging
try:
	from logging.handlers import WatchedFileHandler
except ImportError:
	from logging import FileHandler as WatchedFileHandler

from lvmb import LVMB, LVMBError


__version__ = '0.2'


# Date formating string
dateFmt = "%Y-%m-%d %H:%M:%S.%f"


# State directory
STATE_DIR = os.path.join(os.path.dirname(__file__), '.lm-state')
if not os.path.exists(STATE_DIR):
    os.mkdir(STATE_DIR)
else:
    if not os.path.isdir(STATE_DIR):
        raise RuntimeError("'%s' is not a directory" % STATE_DIR)


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
    except OSError as e:
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
    except OSError as e:
        sys.stderr.write("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)

    # Now I am a daemon!

    # Redirect standard file descriptors.
    si = open(stdin, 'r')
    so = open(stdout, 'a+')
    se = open(stderr, 'a+')
    ## Make a time mark
    mark = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    so.write("===\nLaunched at %s\n===\n" % mark)
    se.write("===\nLaunched at %s\n===\n" % mark)
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())


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
        try:
            data = bytes(data, 'ascii')
        except TypeError:
            pass
        if self.sock is not None:
            self.sock.sendto(data, (self.mcastAddr, self.mcastPort) )
        

def main(args):
    # PID file
    if args.pid_file is not None:
        fh = open(args.pid_file, 'w')
        fh.write("%i\n" % os.getpid())
        fh.close()
        
    # Setup logging
    logger = logging.getLogger(__name__)
    logFormat = logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logFormat.converter = time.gmtime
    if args.log_file is None:
        logHandler = logging.StreamHandler(sys.stdout)
    else:
        logHandler = WatchedFileHandler(args.log_file)
    logHandler.setFormatter(logFormat)
    logger.addHandler(logHandler)
    if args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.addFilter(DuplicateFilter(callback=logger))
    
    # Git information
    try:
        repo = git.Repo(os.path.basename(os.path.abspath(__file__)))
        branch = repo.active_branch.name
        hexsha = repo.active_branch.commit.hexsha
        shortsha = hexsha[-7:]
        dirty = ' (dirty)' if repo.is_dirty() else ''
    except git.exc.GitError:
        branch = 'unknown'
        hexsha = 'unknown'
        shortsha = 'unknown'
        dirty = ''
        
    # Report on who we are
    logger.info('Starting %s with PID %i', os.path.basename(__file__), os.getpid())
    logger.info('Version: %s', __version__)
    logger.info('Revision: %s.%s%s', branch, shortsha, dirty)
    logger.info('All dates and times are in UTC except where noted')
    
    # Connect to the meter
    meter, r120FH, r240FH = None, sys.stdout, sys.stdout
    try:
        meter = LVMB(args.config_file['serial_port'])
        logger.info('Connected to 240V and 120V meters on %s', args.config_file['serial_port'])
    except (LVMBError, serial.serialutil.SerialException) as e:
        meter = None
        logger.warning('Cannot connect to 240V and 120V meters: %s', str(e))
        
    r120FH = open(os.path.join(args.config_file['log_directory'], 'voltage_120.log'), 'a')
    r240FH = open(os.path.join(args.config_file['log_directory'], 'voltage_240.log'), 'a')
    
    # Is there anything to do?
    if meter is None:
        logger.fatal('No voltage meters found, aborting')
        logging.shutdown()
        sys.exit(1)
        
    # Start the data server
    server = dataServer(mcastAddr=args.config_file['multicast']['ip'], mcastPort=int(args.config_file['multicast']['port']), 
                        sendPort=int(args.config_file['multicast']['port'])+1)
    server.start()
    
    # Set the voltage moving average variables
    voltage120 = []
    voltage240 = []
    
    # Setup the event detection variables
    start120, flicker120, outage120 = None, False, False
    start240, flicker240, outage240 = None, False, False
    
    # Load in the state
    ## 120 VAC
    try:
        fh = open(os.path.join(STATE_DIR, 'inPowerFailure120'), 'r')
        t = float(fh.read())
        fh.close()
        
        start120, flicker120, outage120 = t*1.0, t*1.0, t*1.0
        logging.info('Restored a saved 120V power outage from disk')
        
        #os.unlink(os.path.join(STATE_DIR, 'inPowerFailure120'))
    except Exception as e:
        pass
    ## 240 VAC
    try:
        fh = open(os.path.join(STATE_DIR, 'inPowerFailure240'), 'r')
        t = float(fh.read())
        fh.close()
        
        start240, flicker240, outage240 = t*1.0, t*1.0, t*1.0
        logging.info('Restored a saved 240V power outage from disk')
        
        #os.unlink(os.path.join(STATE_DIR, 'inPowerFailure240'))
    except Exception as e:
        pass
        
    # Read from the ports forever
    try:
        t0_120 = 0.0
        t0_240 = 0.0
        
        while True:
            ## Set the (date)time
            tUTC = datetime.utcnow()
            
            ## Read the data
            if meter is not None:
                try:
                    ### Both voltages come in at the same time
                    data240, data120 = meter.read()
                    t = time.time()
                    
                    ### Deal with 120V first
                    v = data120
                    r120FH.write("%.2f  %.1f\n" % (t, v))
                    
                    if v < args.config_file['limits']['120V']['low'] or v > args.config_file['limits']['120V']['high']:
                        logger.warning('120V is out of range at %.1f VAC', v)
                        if start120 is None:
                            start120 = t
                    else:
                        if flicker120 and (t - flicker120) >= args.config_file['events']['outage']:
                            logger.info('120V Flicker cleared')
                            flicker120 = False
                            
                        if outage120 and (t - outage120) >= args.config_file['events']['clear']:
                            logger.info('120V Outage cleared')
                            outage120 = False
                            
                            try:
                                os.unlink(os.path.join(STATE_DIR, 'inPowerFailure120'))
                            except (OSError, IOError) as e:
                                pass
                                
                            server.send("[%s] CLEAR: 120V" % tUTC.strftime(dateFmt))
                            
                        if not flicker120 and not outage120:
                            start120 = None
                            
                    if start120 is not None and not flicker120:
                        age = t - start120
                        if age >= args.config_file['events']['flicker'] and age < args.config_file['events']['outage']:
                            logger.warning('120V has been out of tolerances for %.1f s (flicker)', age)
                            flicker120 = start120*1.0
                            
                            server.send("[%s] FLICKER: 120V" % tUTC.strftime(dateFmt))
                            
                    if start120 is not None and not outage120:
                        age = t - start120
                        if age >= args.config_file['events']['outage']:
                            logger.error('120V has been out of tolerances for %.1f s (outage)', age)
                            outage120 = start120*1.0
                            
                            try:
                                fh = open(os.path.join(STATE_DIR, 'inPowerFailure120'), 'w')
                                fh.write("%.6f" % t)
                                fh.close()
                            except (OSError, IOError) as e:
                                logging.error("Could not write 120V state file: %s", str(e))
                                
                            server.send("[%s] OUTAGE: 120V" % tUTC.strftime(dateFmt))
                            
                    if t-t0_120 > 10.0:
                        logger.debug('120V meter is currently reading %.1f VAC', v)
                        r120FH.flush()
                        t0_120 = t*1.0
                        
                    voltage120.append( v )
                    if len(voltage120) == 4:
                        voltage120 = sum(voltage120) / len(voltage120)
                        server.send("[%s] 120VAC: %.2f" % (tUTC.strftime(dateFmt), voltage120))
                        voltage120 = []
                        
                    ### Now deal with the 240V
                    v = data240
                    r240FH.write("%.2f  %.1f\n" % (t, v))
                    
                    if v < args.config_file['limits']['240V']['low'] or v > args.config_file['limits']['240V']['high']:
                        logger.warning('240V is out of range at %.1f VAC', v)
                        if start240 is None:
                            start240 = t
                    else:
                        if flicker240 and (t - flicker240) >= args.config_file['events']['outage']:
                            logger.info('240V Flicker cleared')
                            flicker240 = False
                            
                        if outage240 and (t - outage240) >= args.config_file['events']['clear']:
                            logger.info('240V Outage cleared')
                            outage240 = False
                            
                            try:
                                os.unlink(os.path.join(STATE_DIR, 'inPowerFailure240'))
                            except (OSError, IOError) as e:
                                pass
                                
                            server.send("[%s] CLEAR: 240V" % tUTC.strftime(dateFmt))
                            
                        if not flicker240 and not outage240:
                            start240 = None
                            
                    if start240 is not None and not flicker240:
                        age = t - start240
                        if age >= args.config_file['events']['flicker'] and age < args.config_file['events']['outage']:
                            logger.warning('240V has been out of tolerances for %.1f s (flicker)', age)
                            flicker240 = start240*1.0
                            
                            server.send("[%s] FLICKER: 240V" % tUTC.strftime(dateFmt))
                            
                    if start240 is not None and not outage240:
                        age = t - start240
                        if age >= args.config_file['events']['outage']:
                            logger.error('240V has been out of tolerances for %.1f s (outage)', age)
                            outage240 = start240*1.0
                            
                            try:
                                fh = open(os.path.join(STATE_DIR, 'inPowerFailure240'), 'w')
                                fh.write("%.6f" % t)
                                fh.close()
                            except (OSError, IOError) as e:
                                logging.error("Could not write 240V state file: %s", str(e))
                                
                            server.send("[%s] OUTAGE: 240V" % tUTC.strftime(dateFmt))
                            
                    if t-t0_240 > 10.0:
                        logger.debug('240V meter is currently reading %.1f VAC', v)
                        r240FH.flush()
                        t0_240 = t*1.0
                        
                    voltage240.append( v )
                    if len(voltage240) == 4:
                        voltage240 = sum(voltage240) / len(voltage240)
                        server.send("[%s] 240VAC: %.2f" % (tUTC.strftime(dateFmt), voltage240))
                        voltage240 = []
                        
                except (TypeError, RuntimeError) as e:
                    logger.warning('Error parsing voltage data: %s', str(e), exc_info=True)
                    
                except LVMBError as e:
                    logger.warning('Error reading from voltage meter: %s', str(e))
                    
            ## Sleep a bit
            time.sleep(0.2)
            
    except KeyboardInterrupt:
        logger.info("Interrupt received, shutting down")
        
        server.stop()
        
        if meter is not None:
            meter.close()
            
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
    parser = argparse.ArgumentParser(
        description='read data from a LWA voltage monitoring device and save the data to a log',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
            )
    parser.add_argument('-c', '--config-file', type=str, default='defaults.json',
                        help='filename for the configuration file')
    parser.add_argument('-p', '--pid-file', type=str,
                        help='file to write the current PID to')
    parser.add_argument('-l', '--log-file', type=str,
                        help='file to log operational status to')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='print debug messages as well as info and higher')
    parser.add_argument('-f', '--foreground', action='store_true',
                        help='run in the foreground, do not daemonize')
    args = parser.parse_args()
    
    # Parse the configuration file
    with open(args.config_file, 'r') as ch:
        args.config_file = json.loads(json_minify.json_minify(ch.read()))
        
    if not args.foreground:
        daemonize('/dev/null','/tmp/lm-stdout','/tmp/lm-stderr')
        
    main(args)
    
