#!/usr/bin/python
# Example using a character LCD plate.
import time
import math
import threading

import Adafruit_CharLCD as LCD
from mpd import MPDClient

def plate_handler():
	global vol
	global event_lock
	global next_event
	global prev_event
	global restart_event
	global pause_event
	global volume_event
	global text_lock
	global running
	global title_text
	global line2

	STATE_IDLE = 0
	STATE_HOLDOFF = 1
	STATE_DEBOUNCE = 2
	state = STATE_IDLE
	debounce_button = 0
	last_prev = -1
	count = 0
	offset = 0
	try:
		while running:
			if state == STATE_DEBOUNCE:
				if (not lcd.is_pressed(debounce_button)):
					state = STATE_IDLE
			if state == STATE_HOLDOFF:
				state = STATE_DEBOUNCE
			if state == STATE_IDLE:
				if (lcd.is_pressed(LCD.UP)):
					event_lock.acquire()
					vol += 5
					volume_event.set()
					event_lock.release()
					state = STATE_HOLDOFF
					debounce_button = LCD.UP
				if (lcd.is_pressed(LCD.DOWN)):
					event_lock.acquire()
					vol -= 5
					volume_event.set()
					event_lock.release()
					state = STATE_HOLDOFF
					debounce_button = LCD.DOWN
				if (lcd.is_pressed(LCD.RIGHT)):
					event_lock.acquire()
					next_event.set()
					event_lock.release()
					state = STATE_HOLDOFF
					debounce_button = LCD.RIGHT
				if (lcd.is_pressed(LCD.LEFT)):
					event_lock.acquire()
					if time.clock() - last_prev < 2:
						prev_event.set()
					else:
						restart_event.set()					
					event_lock.release()
					state = STATE_HOLDOFF
					debounce_button = LCD.LEFT
					last_prev = time.clock()
				if (lcd.is_pressed(LCD.SELECT)):
					event_lock.acquire()
					pause_event.set()
					event_lock.release()
					state = STATE_HOLDOFF
					debounce_button = LCD.SELECT

			# Handle the LCD
			count += 1
			if count > 10 and text_lock.acquire(False):
				count = 0
				lcd.home()
				lcd.message(
					(title_string[offset:offset+16] + title_string[0:offset-len(title_string)])[0:16] + "\n" +
					#stats['state'] + " vol: " + stats['volume'] + " " +
					line2
					)
				offset = offset + 1
				if offset > len(title_string):
					offset = 0
				text_lock.release()
			time.sleep(.05)
	except:
		print("BUTTON WATCHER DIED!")
		pass
	return


print("Connecting...")
client = MPDClient()
client.timeout = 10
client.idletimeout = None
client.connect("localhost",6600)
stats = client.status()
vol = 0
offset = 0

# Initialize the LCD using the pins 
lcd = LCD.Adafruit_CharLCDPlate()
lcd.create_char(1,[0,0,0,0,0,0,0,30])
lcd.create_char(2,[0,0,0,0,0,0,16,30])
lcd.create_char(3,[0,0,0,0,8,8,16+8,30])
lcd.create_char(4,[0,0,4,4,8+4,8+4,16+8+4,30])
lcd.create_char(5,[2,2,4+2,4+2,8+4+2,8+4+2,16+8+4+2,30])



# Show some basic colors.
lcd.set_color(1.0, 1.0, 1.0)
lcd.clear()
lcd.message('Getting player\nstate...')

print 'Press Ctrl-C to quit.'
last_ping = time.clock()
last_tick = time.clock()
last_song_id = -1
title_string = "unknown"
title_string += "                "[0:16-len(title_string)]
line2 = ""
song = False

next_event = threading.Event()
prev_event = threading.Event()
restart_event = threading.Event()
pause_event = threading.Event()
volume_event = threading.Event()
event_lock = threading.Lock()
text_lock = threading.Lock()

running = True
plate_watcher = threading.Thread(target=plate_handler)
plate_watcher.daemon = True
plate_watcher.start()

stats = client.send_status()

try:
	while True:
		stats = client.fetch_status()
	
		event_lock.acquire()
		if next_event.is_set():
			next_event.clear()
			client.next()
		if prev_event.is_set():
			prev_event.clear()
			client.previous()
		if restart_event.is_set():
			restart_event.clear()
			try:
				client.seek(stats['song'],0)
			except:
				print("Can't seek to beginning!")
		if pause_event.is_set():				
			pause_event.clear()
			if stats['state'] == "stop":
				client.play()
			if stats['state'] == "play":
				client.pause(1)
			if stats['state'] == "pause":
				client.pause(0)
		if volume_event.is_set():
			volume_event.clear()
			newvol = int(stats['volume']) + vol
			if newvol > 100:
				newvol = 100
			if newvol < 0:
				newvol = 0
			client.setvol(newvol)	
			vol = 0
		event_lock.release()
	
		if time.clock()-last_ping > 5:
			client.ping()
			last_ping = time.clock()
	
		if 'songid' in stats:
			text_lock.acquire()
			if stats['songid'] != last_song_id:
				song = client.currentsong()
				last_song_id = song['id']
				title_string = song.get('title',"No Title") + " [" + song.get('artist',"No Artist") + "] "
				title_string += "                "[0:16-len(title_string)]
				offset = 0
			last_tick = time.clock()
			if 'elapsed' in stats:
				minutes = int(float(stats['elapsed'])/60)
				seconds = int(math.fmod(float(stats['elapsed']),60.0))
			else:
				minutes = 0
				seconds = 0
			volchar = int(float(stats['volume'])/100*4)+1
			if volchar<1:
				volchar = 1
			if volchar > 5:
				volchar = 5

			line2 = "{:d}:{:02d}".format(minutes,seconds)
			line2 += "                "[0:16-len(line2)-2]
			line2 += " " + chr(volchar)
			text_lock.release()

		client.send_status()
		time.sleep(.5)

except KeyboardInterrupt:
	pass #from here on out we're bailing

try:
	event_lock.release() # Try and clear the lock, just in case.
except:
	pass

print "Disconnecting..."
running = False
client.disconnect()
print "Shutting down plate_watcher..."
plate_watcher.join()
print "Cleaning up LCD..."
lcd.set_color(0.0, 0.0, 0.0)
lcd.clear()
print "Bye!"

