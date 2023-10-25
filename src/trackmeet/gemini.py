# SPDX-License-Identifier: MIT
"""Gemini (numeric) scoreboard sender.

 Output information to a pair of numeric, 9 character Gemini boards.
 Boards have the following layout:

   ---------------------
  | N N N   T:T:T:T:T:T |	N... is usually a rider no
   ---------------------	T... is time, punctuation may be ' ' , : or .

 Trackmeet events output the following formats:

 Bib, Rank & Time for flying 200, and elimination (show_brt):
 Content is the same on both boards

   ---------------------
  | 2 3     4   1 0.4 5 |	Rider 23, ranked 4th, 10.45 sec
   ---------------------

   ---------------------
  | 1 2 3               |	Rider 123 eliminated
   ---------------------

 "Dual" for ITT and pursuit race (show_dual):
 Allows for runtime up to 9:59.999, rolling time and downtime

   ---------------------
  | 1 2 3   3:4 5.6 7 8 |	Front straight, rider 123, 3:45.678
   ---------------------
  | 4 5     1:2 2.9 8 0 |	Back straight, rider 45, 1:22.980
   ---------------------

 "Running Time" for generic running time display (show_runtime):
 Content is the same on both boards, use bib to set first three chars

   ---------------------
  | 2 1     1 2:3 2.1   |	eg, 21 laps to go, elapsed 12:32.1
   ---------------------

 "Clock" for time of day (show_clock):
 Content is the same on both boards

   ---------------------
  |         1 2:4 5:3 7 |	Time of day: 12:45:37
   ---------------------

 "Lap" for display of lap on three-sided displays (show_lap)
 Content is the same on both boards

   ---------------------
  | 1 2 3   1 2:3 1:2 3 |	123 laps to go
   ---------------------

"""

import threading
import queue
import logging
import serial
import sys

from metarace import unt4
from metarace import tod
from metarace import strops

# module logger
_log = logging.getLogger('gemini')
_log.setLevel(logging.DEBUG)

# consts
_GEMBAUD = 9600
_DEFPORT = '/dev/ttyUSB1'
_ENCODING = 'ascii'
_GEMHEAD = chr(unt4.SOH[0]) + chr(unt4.DC4[0])
_GEMHOME = chr(unt4.STX[0]) + chr(0x08)
_GEMFOOT = chr(unt4.EOT[0])


class gemini(threading.Thread):
    """Gemini sender thread."""

    def clear(self):
        """Clear scb."""
        self.bib = ''
        self.bib1 = ''
        self.rank = ''
        self.time = ''
        self.time1 = ''
        self.lap = ''
        self.lmsg = ''
        self.write(unt4.GENERAL_CLEARING.pack())

    def send_msg(self, msg, mtype='S', charoff='0', msg1=None):
        msg0 = msg
        if msg1 is None:
            msg1 = msg
        nmsg = (
            _GEMHEAD  # front straight
            + mtype + '0' + charoff + _GEMHOME + msg0 + _GEMFOOT +
            _GEMHEAD  # back straight
            + mtype + '0' + charoff + _GEMHOME + chr(unt4.LF[0])  # line 2
            + msg1 + _GEMFOOT)
        if nmsg != self.lmsg:
            self.write(nmsg)
            self.lmsg = nmsg

    def reset_fields(self):
        """Clear out the gemini state fields."""
        self.bib = ''
        self.bib1 = ''
        self.rank = ''
        self.rank1 = ''
        self.time = ''
        self.time1 = ''

    def show_lap(self):
        self.lmsg = ''  # always write out lap to allow redraw
        lstr = strops.truncpad(self.lap, 3, 'r')
        msg = (lstr + chr(unt4.STX[0]) + lstr[0:2] + ':' + lstr[2] + lstr[0] +
               ':' + lstr[1:3] + '.  ')
        self.send_msg(msg)

    def show_brt(self):
        msg = (
            strops.truncpad(self.bib, 3) + chr(unt4.STX[0]) +
            strops.truncpad(str(self.rank), 1) + '  '  # the 'h:' padding
            + self.time.rjust(5))
        self.send_msg(msg)

    def show_dual(self):
        line0 = (strops.truncpad(self.bib, 3) + chr(unt4.STX[0]) +
                 strops.truncpad(self.time, 12, 'r', ellipsis=False))
        line1 = (strops.truncpad(self.bib1, 3) + chr(unt4.STX[0]) +
                 strops.truncpad(self.time1, 12, 'r', ellipsis=False))
        self.send_msg(line0, 'R', '3', msg1=line1)  # xxx-5:02.6-x

    def set_rank(self, rank):
        if rank.isdigit() and len(rank) <= 1:
            self.rank = rank
        else:
            self.rank = ''

    def set_bib(self, bib, lane=False):  # True/1/something -> lane 1
        if lane:
            self.bib1 = bib
        else:
            self.bib = bib

    def set_time(self, time, lane=False):
        if lane:
            self.time1 = time
        else:
            self.time = time

    def show_clock(self):
        msg = (
            '   '  # bib padding
            + chr(unt4.STX[0]) +
            strops.truncpad(self.time, 12, 'r', ellipsis=False))
        self.send_msg(msg, 'R')  # -2:34:56xxxx

    def rtick(self, ttod, places=3):
        """Convenience wrapper on set time/show runtime."""
        self.set_time(ttod.omstr(places))
        self.show_runtime()

    def dtick(self, ttod, places=3, lane=False):
        """Convenience wrapper on set time/show dualtime."""
        self.set_time(ttod.omstr(places), lane)
        self.show_dual()

    def ctick(self, ttod):
        """Convenience wrapper on set time/show clock."""
        self.set_time(ttod.omstr(0))
        self.show_clock()

    def set_lap(self, lap=''):
        """Set and show the provided lap."""
        self.lap = str(lap)
        self.show_lap()

    def show_runtime(self):
        msg = (strops.truncpad(self.bib, 3) + chr(unt4.STX[0]) +
               strops.truncpad(self.time, 12, 'r', ellipsis=False))
        self.send_msg(msg, 'R', '2')  # xxx-5:02.6-x

    def __init__(self, port=None):
        """Constructor."""
        threading.Thread.__init__(self, daemon=True)
        self._port = None
        self._ignore = False
        self._queue = queue.Queue()
        self._running = False

        self.bib = ''
        self.bib1 = ''
        self.rank = ''
        self.rank1 = ''
        self.time = ''
        self.time1 = ''
        self.lap = ''
        self.lmsg = ''

        if port is not None:
            self.setport(port)

    def write(self, msg=None):
        """Send the provided msg to the scoreboard."""
        self._queue.put_nowait(('MSG', msg))

    def exit(self, msg=None):
        """Request thread termination."""
        self._running = False
        self._queue.put_nowait(('EXIT', msg))

    def wait(self):
        """Suspend calling thread until cqueue is empty."""
        self._queue.join()

    def setport(self, port=None):
        """Dump command queue content and (re)open port."""
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass
        self._queue.put_nowait(('PORT', port))

    def set_ignore(self, ignval=False):
        """Set or clear the ignore flag."""
        self._ignore = bool(ignval)

    def connected(self):
        """Return true if SCB connected."""
        return self._port is not None and self._running

    def run(self):
        """Called via threading.Thread.start()."""
        self._running = True
        _log.debug('Starting')
        while self._running:
            m = self._queue.get()
            self._queue.task_done()
            try:
                if m[0] == 'MSG' and not self._ignore and self._port:
                    #_log.debug(u'Send: %r', m[1])
                    self._port.write(m[1].encode(_ENCODING, 'ignore'))
                elif m[0] == 'EXIT':
                    _log.debug('Request to close: %s', m[1])
                    self._running = False
                elif m[0] == 'PORT':
                    if self._port is not None:
                        self._port.close()
                        self._port = None
                    if m[1] is not None and m[1] != '' and m[1] != 'NULL':
                        _log.debug('Re-Connect port: %s', m[1])
                        self._port = serial.Serial(m[1],
                                                   _GEMBAUD,
                                                   rtscts=0,
                                                   timeout=0.2)
                    else:
                        _log.debug('Not connected.')

            except IOError as e:
                _log.error('IO Error: %s', e)
                if self._port is not None:
                    self._port.close()
                self._port = None
            except Exception as e:
                _log.error('%s: %s', e.__class__.__name__, e)
        if self._port is not None:
            self._port.close()
        _log.debug('Exiting')
