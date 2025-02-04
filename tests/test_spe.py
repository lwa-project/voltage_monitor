import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import json
import time
from datetime import datetime, timedelta
import threading
import tempfile
import shutil

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))

from sendPowerEmail import _connect, DLVM, sendEmail, get_uptime

class TestSendPowerEmail(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for state files
        self.temp_dir = tempfile.mkdtemp()
        
        # Mock arguments
        self.args = Mock()
        self.args.address = '224.168.2.10',
        self.args.port=7165,
        self.args.pid_file = None
        
    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.temp_dir)
        
    def _get_mock_socket(self, mock_events):
        """Given a list of events, create a mock socket that you can recvfrom()"""
        mock_sock = Mock()
        mock_events.append(KeyboardInterrupt)
        mock_events = iter(mock_events)
        def timed_recvfrom(value):
            time.sleep(0.25)  # Simulate server delays
            next_value = next(mock_events)
            if next_value is KeyboardInterrupt:
                raise KeyboardInterrupt
            return (next_value, ('127.0.0.1',1))
        mock_sock.recvfrom.side_effect = timed_recvfrom
        return mock_sock
        
    @patch('sendPowerEmail.DLVM')
    @patch('sendPowerEmail._connect')
    @patch('sendPowerEmail.sendEmail')
    def test_normal_conditions(self, mock_send, mock_connect, mock_dlvm):
        """Test normal conditions"""
        events = []
        for i in range(10):
            t = datetime.utcnow() + timedelta(seconds=5+i)
            events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] 120VAC: Normal")
        mock_sock = self._get_mock_socket(events)
        mock_connect.return_value = mock_sock
        
        # Run main with mocked components
        with patch('sendPowerEmail.STATE_DIR', new=self.temp_dir):
            DLVM(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_sock.recvfrom.called)
        self.assertFalse(mock_send.called)
        
    @patch('sendPowerEmail.DLVM')
    @patch('sendPowerEmail._connect')
    @patch('sendPowerEmail.sendEmail')
    def test_notify_flicker(self, mock_send, mock_connect, mock_dlvm):
        """Test notification when there is a flicker"""
        events = []
        t = datetime.utcnow() + timedelta(seconds=5)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] 120VAC: Normal")
        t = datetime.utcnow() + timedelta(seconds=6)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] FLICKER: Bad")
        mock_sock = self._get_mock_socket(events)
        mock_connect.return_value = mock_sock
        
        # Run main with mocked components
        with patch('sendPowerEmail.STATE_DIR', new=self.temp_dir):
            DLVM(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_sock.recvfrom.called)
        self.assertTrue(mock_send.called)
        
        # Verify a flicker notification was sent
        flicker_messages = [
            call[0][0] for call in mock_send.call_args_list 
            if 'Flicker' in call[0][0]
        ]
        self.assertTrue(len(flicker_messages) > 0)
        
    @patch('sendPowerEmail.DLVM')
    @patch('sendPowerEmail._connect')
    @patch('sendPowerEmail.sendEmail')
    @patch('sendPowerEmail.get_uptime')
    def test_notify_outage(self, mock_uptime, mock_send, mock_connect, mock_dlvm):
        """Test notification when there is an outage"""
        events = []
        t = datetime.utcnow() + timedelta(seconds=5)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] 120VAC: Normal")
        t = datetime.utcnow() + timedelta(seconds=6)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] FLICKER: Bad")
        t = datetime.utcnow() + timedelta(seconds=7)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] OUTAGE: Really bad")
        t = datetime.utcnow() + timedelta(seconds=7)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] CLEAR: Better")
        mock_sock = self._get_mock_socket(events)
        mock_connect.return_value = mock_sock
        
        mock_uptime.return_value = 5
        
        # Run main with mocked components
        with patch('sendPowerEmail.STATE_DIR', new=self.temp_dir):
            DLVM(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_sock.recvfrom.called)
        self.assertTrue(mock_send.called)
        
        # Verify an outage notification was sent
        outage_messages = [
            call[0][0] for call in mock_send.call_args_list 
            if 'Outage' in call[0][0]
        ]
        self.assertTrue(len(outage_messages) > 0)
        
        # Verify a clear notification was sent
        clear_messages = [
            call[0][0] for call in mock_send.call_args_list 
            if 'Clear' in call[0][0]
        ]
        self.assertTrue(len(clear_messages) > 0)
        
    @patch('sendPowerEmail.DLVM')
    @patch('sendPowerEmail._connect')
    @patch('sendPowerEmail.sendEmail')
    @patch('sendPowerEmail.get_uptime')
    def test_outage_state(self, mock_uptime, mock_send, mock_connect, mock_dlvm):
        """Test notification when an outage is long enough to restart the computer"""
        
        #
        # Part 1 - The initial outage
        #
        
        events = []
        t = datetime.utcnow() + timedelta(seconds=5)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] 120VAC: Normal")
        t = datetime.utcnow() + timedelta(seconds=6)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] FLICKER: Bad")
        t = datetime.utcnow() + timedelta(seconds=7)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] OUTAGE: Really bad")
        mock_sock = self._get_mock_socket(events)
        mock_connect.return_value = mock_sock
        
        mock_uptime.return_value = 5
        
        # Run main with mocked components
        with patch('sendPowerEmail.STATE_DIR', new=self.temp_dir):
            DLVM(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_sock.recvfrom.called)
        self.assertTrue(mock_send.called)
        
        # Verify an outage notification was sent
        outage_messages = [
            call[0][0] for call in mock_send.call_args_list 
            if 'Outage' in call[0][0]
        ]
        self.assertTrue(len(outage_messages) > 0)
        
        #
        # Part 2 - Starting back up after the outage
        #
        
        events = []
        t = datetime.utcnow() + timedelta(seconds=7)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] 120VAC: Normal")
        t = datetime.utcnow() + timedelta(seconds=8)
        events.append(f"[{t.strftime('%Y-%m-%d %H:%M:%S.%f')}] OUTAGE: Really bad")
        mock_sock = self._get_mock_socket(events)
        mock_connect.return_value = mock_sock
        
        mock_uptime.return_value = 6
        
        # Run main with mocked components
        with patch('sendPowerEmail.STATE_DIR', new=self.temp_dir):
            DLVM(self.args)
            
        # Verify behaviors
        self.assertTrue(mock_sock.recvfrom.called)
        self.assertTrue(mock_send.called)
        
        # Verify a clear notification was sent
        clear_messages = [
            call[0][0] for call in mock_send.call_args_list 
            if 'Clear' in call[0][0]
        ]
        self.assertTrue(len(clear_messages) > 0)
