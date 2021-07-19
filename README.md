Line (Voltage) Monitoring Software
==================================

This directory contains a collection of software for interfacing with a
Arduino connected to a custom PCB for monitoring AC line voltage.

This software depends on the following python modules:
  * pySerial
  * pytz
  * wxPython

Contents
--------
lvmb.py - Python module for interfacing with the Arduino and reading the voltage.

lineMonitor.py - Python script for logging line voltages.
