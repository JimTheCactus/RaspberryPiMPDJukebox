#!/usr/bin/python
# Example using a character LCD plate.
import time
import math
import threading
import Queue

import Adafruit_CharLCD as LCD
from mpd import MPDClient

ACTION_VOLUME_UP = 1
ACTION_VOLUME_DOWN = 2
ACTION_NEXT = 3
ACTION_PREV = 4
ACTION_REWIND = 5
ACTION_PLAYPAUSE = 6

# Thread for managing the LCD
def plate_handler():
	# Variables that cross the thread boundary
	global vol
	global running
	global title_text
	global line2

	# Locks and events for communication
	global action_queue
	global reset_event
	global text_lock

	# State machine contants
	STATE_IDLE = 0
	STATE_HOLDOFF = 1
	STATE_DEBOUNCE = 2

	# Initialize the state machine
	state = STATE_IDLE # Waiting for button
	debounce_button = 0 # No buttons waiting
	last_prev = -1 # Set the double press counter to something impossibly small
	count = 0 # LCD Refresh decimator
	offset = 0 # Text offset on line 1

	try:
		while running: # So long as the parent is going...
			if state == STATE_DEBOUNCE: # Wait for the user to let go.
				if (not lcd.is_pressed(debounce_button)):
					state = STATE_IDLE
			if state == STATE_HOLDOFF: # Wait an extra tick to let chatter settle out.
				state = STATE_DEBOUNCE
			if state == STATE_IDLE: # Check to see what buttons are pressed
				if (lcd.is_pressed(LCD.UP)):
					action_queue.put(ACTION_VOLUME_UP)
					state = STATE_HOLDOFF
					debounce_button = LCD.UP
				if (lcd.is_pressed(LCD.DOWN)):
					action_queue.put(ACTION_VOLUME_DOWN)
					state = STATE_HOLDOFF
					debounce_button = LCD.DOWN
				if (lcd.is_pressed(LCD.RIGHT)):
					action_queue.put(ACTION_NEXT)
					state = STATE_HOLDOFF
					debounce_button = LCD.RIGHT
				if (lcd.is_pressed(LCD.LEFT)):
					if time.clock() - last_prev < 2:
						action_queue.put(ACTION_PREV)
					else:
						action_queue.put(ACTION_REWIND)
					state = STATE_HOLDOFF
					debounce_button = LCD.LEFT
					last_prev = time.clock()
				if (lcd.is_pressed(LCD.SELECT)):
					action_queue.put(ACTION_PLAYPAUSE)
					state = STATE_HOLDOFF
					debounce_button = LCD.SELECT

			# Handle the LCD
			count += 1
			if count > 5 and text_lock.acquire(False): # If we've skipped enough cycles and can get to the text
				if reset_event.is_set():
					reset_event.clear()
					offset = 0
				count = 0 # Reset the decimator
				lcd.home() # Move to the top
				lcd.message(
					(title_string[offset:offset+16] + title_string[0:offset-len(title_string)])[0:16] + "\n" +
					#stats['state'] + " vol: " + stats['volume'] + " " +
					line2
					)
				# Increment and loop (if necessary) the offset
				offset = offset + 1
				if offset > len(title_string):
					offset = 0
				# Let go of the text
				text_lock.release()
			# Delay a bit to avoid saturating the processor.
			time.sleep(.05)
	except:
		print("BUTTON WATCHER DIED!")
		pass
	return

print('Initializing hardware and drivers..')

# Initialize the LCD
lcd = LCD.Adafruit_CharLCDPlate()
# Add the volume indicators
lcd.create_char(1,[0,0,0,0,0,0,0,30])
lcd.create_char(2,[0,0,0,0,0,0,16,30])
lcd.create_char(3,[0,0,0,0,8,8,16+8,30])
lcd.create_char(4,[0,0,4,4,8+4,8+4,16+8+4,30])
lcd.create_char(5,[2,2,4+2,4+2,8+4+2,8+4+2,16+8+4+2,30])

# Clear the screen
lcd.clear()
# Turn on the backlight
lcd.set_color(1.0, 1.0, 1.0)
# And place some initial text on the screen
lcd.message('Starting...')

reset_event = threading.Event()
action_queue = Queue.Queue()
text_lock = threading.Lock()

running = True
plate_watcher = threading.Thread(target=plate_handler)
plate_watcher.daemon = True
plate_watcher.start()

title_string = "Connecting"
title_string += "                "[0:16-len(title_string)]
line2 = ""

print('Connecting...')
# Connect to local MPD server
client = MPDClient()
client.timeout = 10
client.idletimeout = None
client.connect("localhost",6600)


print 'Connected. Initializing player...'
# Get the initial state
stats = client.status()
last_ping = time.clock()
last_song_id = -1
song = False


print 'Initialization finished. Player active!'
print 'Press Ctrl-C to quit.'

try:
	stats = client.send_status() # Loop needs an initial request to work.
	while True:
		stats = client.fetch_status() # Get the results of the last request
		
		while not action_queue.empty():
			action = action_queue.get(False)
			if action == ACTION_VOLUME_UP:
				newvol = int(stats['volume']) + 5
				if newvol > 100:
					newvol = 100
				client.setvol(newvol)	
			elif action == ACTION_VOLUME_DOWN:
				newvol = int(stats['volume']) - 5
				if newvol < 0:
					newvol = 0
				client.setvol(newvol)
			elif action == ACTION_NEXT:
				client.next()
			elif action == ACTION_PREV:
				client.previous()
			elif action == ACTION_REWIND:
				try:
					client.seek(stats['song'],0)
				except:
					print("Can't seek to beginning!")
			elif action == ACTION_PLAYPAUSE:
				if stats['state'] == "stop":
					client.play()
				if stats['state'] == "play":
					client.pause(1)
				if stats['state'] == "pause":
					client.pause(0)
			else:
				print('Unexpected action queue item: {0}'.format(action))
	
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
				reset_event.set()
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

print "Disconnecting..."
running = False
client.disconnect()
print "Shutting down plate_watcher..."
plate_watcher.join()
print "Cleaning up LCD..."
lcd.set_color(0.0, 0.0, 0.0)
lcd.clear()
print "Bye!"

