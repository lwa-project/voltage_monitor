import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import json
import time
from datetime import datetime
import threading
import tempfile
import shutil

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voltageMonitor import main, dataServer
from lvmb import LVMB, LVMBError

class TestVoltageMonitor(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for state files
        self.temp_dir = tempfile.mkdtemp()
        
        # Basic config for testing
        self.config = {
            "serial_port": "/dev/fake",
            "multicast": {
                "ip": "224.168.2.10",
                "port": 7165
            },
            "log_directory": self.temp_dir,
            "limits": {
                "120V": {
                    "low": 108.0,
                    "high": 132.0
                },
                "240V": {
                    "low": 216.0,
                    "high": 264.0
                }
            },
            "events": {
                "flicker": 0.0,
                "outage": 0.5,
                "clear": 3.0
            }
        }

        # Mock arguments
        self.args = Mock()
        self.args.config_file = self.config
        self.args.pid_file = None
        self.args.log_file = None
        self.args.debug = False

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.temp_dir)
        
    def _get_mock_device(self, mock_readings):
        """Given a list of readings, create a mock Arduino device that reads
        those out.  At the end of a list a KeyboardInterrupt will be sent."""
        mock_device = Mock()
        mock_readings.append(KeyboardInterrupt)
        mock_readings = iter(mock_readings)
        def timed_read():
            time.sleep(0.25)  # Simulate device read time
            next_value = next(mock_readings)
            if next_value is KeyboardInterrupt:
                raise KeyboardInterrupt
            return next_value
        mock_device.read.side_effect = timed_read
        return mock_device
        
    @patch('voltageMonitor.LVMB')
    @patch('voltageMonitor.dataServer')
    def test_normal_voltage_readings(self, mock_server, mock_lvmb):
        """Test normal voltage readings within limits"""
        # Set up mock LVMB to return normal voltage readings
        mock_device = self._get_mock_device([
            (240.0, 120.0),  # Normal readings
            (238.0, 119.0),
            (238.0, 119.0),
            (236.0, 118.0),
            (240.0, 120.0),
        ])
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance

        # Run main with mocked components
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_device.read.called)
        self.assertTrue(mock_server_instance.send.called)
        
        # Verify no warnings or errors were sent
        for call in mock_server_instance.send.call_args_list:
            message = call[0][0]
            self.assertNotIn('FLICKER', message)
            self.assertNotIn('OUTAGE', message)

    @patch('voltageMonitor.LVMB')
    @patch('voltageMonitor.dataServer')
    def test_voltage_flicker(self, mock_server, mock_lvmb):
        """Test detection of voltage flicker"""
        # Set up mock LVMB to simulate a voltage flicker
        mock_device = self._get_mock_device([
            (240.0, 120.0),  # Normal
            (200.0, 100.0),  # Below limits (flicker)
            (200.0, 100.0),
            (240.0, 120.0),  # Back to normal
            (240.0, 120.0),
        ])
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance

        # Run main
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify flicker was detected and reported
        flicker_messages = [
            call[0][0] for call in mock_server_instance.send.call_args_list 
            if 'FLICKER' in call[0][0]
        ]
        self.assertTrue(len(flicker_messages) > 0)

    @patch('voltageMonitor.LVMB')
    @patch('voltageMonitor.dataServer')
    def test_voltage_outage(self, mock_server, mock_lvmb):
        """Test detection of voltage outage"""
        # Set up mock LVMB to simulate a voltage outage
        readings = [(240.0, 120.0)]  # Start normal
        
        # Add readings for sustained low voltage
        for _ in range(20):  # Enough readings to trigger outage
            readings.append((190.0, 90.0))
        mock_device = self._get_mock_device(readings)
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance
        
        # Run main
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify outage was detected and reported
        outage_messages = [
            call[0][0] for call in mock_server_instance.send.call_args_list 
            if 'OUTAGE' in call[0][0]
        ]
        self.assertTrue(len(outage_messages) > 0)
        
    @patch('voltageMonitor.LVMB')
    @patch('voltageMonitor.dataServer')
    def test_voltage_outage_state(self, mock_server, mock_lvmb):
        """Test state detection of voltage outage"""
        
        #
        # Part 1 - The initial outage
        #
        
        # Set up mock LVMB to simulate a voltage outage
        readings = [(240.0, 120.0)]  # Start normal
        
        # Add readings for sustained low voltage
        for _ in range(20):  # Enough readings to trigger outage
            readings.append((190.0, 90.0))
        mock_device = self._get_mock_device(readings)
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance
        
        # Run main
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify outage was detected and reported
        outage_messages = [
            call[0][0] for call in mock_server_instance.send.call_args_list 
            if 'OUTAGE' in call[0][0]
        ]
        self.assertTrue(len(outage_messages) > 0)
        
        #
        # Part 2 - Starting back up after the outage
        #
        
        # Set up mock LVMB to simulate a voltage outage
        readings = [(240.0, 120.0)]*30  # All normal
        mock_device = self._get_mock_device(readings)
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance
        
        # Run main
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify outage was detected and reported
        clear_messages = [
            call[0][0] for call in mock_server_instance.send.call_args_list 
            if 'CLEAR' in call[0][0]
        ]
        self.assertTrue(len(clear_messages) > 0)
        
    @patch('voltageMonitor.LVMB')
    @patch('voltageMonitor.dataServer')
    def test_device_error_handling(self, mock_server, mock_lvmb):
        """Test handling of device read errors"""
        # Set up mock LVMB to simulate device errors
        mock_device = self._get_mock_device([
            (240.0, 120.0),  # Normal reading
            LVMBError("Communication error"),  # Device error
            (240.0, 120.0),  # Recovered
        ])
        mock_lvmb.return_value = mock_device

        # Set up mock server
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance

        # Run main
        with patch('voltageMonitor.STATE_DIR', new=self.temp_dir):
            main(self.args)
            
        # Verify error was handled gracefully
        self.assertTrue(mock_device.read.call_count > 1)

if __name__ == '__main__':
    unittest.main()
