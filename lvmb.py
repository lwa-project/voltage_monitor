# -*- coding: utf-8 -*-

"""
Simple interface to the Arduino Nano on the LWA voltage monitoring board

$Rev$
$LastChangedBy$
$LastChangedDate$
"""

import serial


class LVMBError(Exception):
    """
    Base exception class for LVM class.
    """

class LVMBReadError(LVMBError):
    """
    Unable to obtain voltage measurements in the allotted time.
    """


class LVMB(object):
    """
    Simple tp4000zc.Dmm-like interface to the Arduino Nano running on the LWA 
    voltage monitoring board.
    """

    def __init__(self, port='/dev/ttyUSB0', retries=3, timeout=1.0):
        self.port = serial.Serial(port, baudrate=9600, timeout=timeout)
        self.retries = retries # the number of times it's allowed to retry to get valid line
        
    def close(self):
        """
        Close out the serial connection to the Arduino.
        """
        
        self.port.close()
        
    def read(self):
        """
        Read in the current 240 VAC and 120 VAC voltages and return as a two-
        element tuple.
        """
        
        success = False
        for attempt in range(self.retries):
            try:
                line = self.port.readline()
                v240, v120 = [float(v) for v in line.split(None, 1)]
                success = True
                break
            except (serial.serialutil.SerialException, ValueError, IndexError):
                pass
                
        if not success:
            raise LVMBReadError("Failed to read voltages")
            
        return v240, v120
        
