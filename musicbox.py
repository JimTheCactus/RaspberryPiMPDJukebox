#!/usr/bin/python
# Example using a character LCD plate.
import time
import math
import threading
import Queue
import atexit

import Adafruit_CharLCDPlate as LCD
from mpd import MPDClient

# Constants for the action queue.
ACTION_VOLUME_UP = 1
ACTION_VOLUME_DOWN = 2
ACTION_NEXT = 3
ACTION_PREV = 4
ACTION_REWIND = 5
ACTION_PLAYPAUSE = 6
ACTION_SCREEN_TOGGLE = 7

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
	global lcd

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
	buttons = 0 # Initialize the buttons value

	try:
		while running: # So long as the parent is going...
			if state == STATE_DEBOUNCE: # Wait for the user to let go.
				if (not lcd.buttonPressed(debounce_button)):
					if debounce_button == lcd.SELECT: # if they pressed down select
						if time.time()-hold_time > 2: # and held it for 2 seconds
							action_queue.put(ACTION_SCREEN_TOGGLE) # toggle the screen
						else:
							action_queue.put(ACTION_PLAYPAUSE) # Otherwise, toggle the play state.
					state = STATE_IDLE
			if state == STATE_HOLDOFF: # Wait an extra tick to let chatter settle out.
				hold_time = time.time()
				state = STATE_DEBOUNCE
			if state == STATE_IDLE: # Check to see what buttons are pressed
				buttons = lcd.buttons()
				if ((buttons >> lcd.UP) & 1):
					action_queue.put(ACTION_VOLUME_UP)
					state = STATE_HOLDOFF
					debounce_button = lcd.UP
				if ((buttons >> lcd.DOWN) & 1):
					action_queue.put(ACTION_VOLUME_DOWN)
					state = STATE_HOLDOFF
					debounce_button = lcd.DOWN
				if ((buttons >> lcd.RIGHT) & 1):
					action_queue.put(ACTION_NEXT)
					state = STATE_HOLDOFF
					debounce_button = lcd.RIGHT
				if ((buttons >> lcd.LEFT) & 1):
					# If it's been less than 2 seconds since the button was last pressed
					if time.time() - last_prev < 2:
						# Go to the last track
						action_queue.put(ACTION_PREV)
					else:
						# Otherwise Rewind
						action_queue.put(ACTION_REWIND)

					# Record the new time for the last press
					last_prev = time.time()

					state = STATE_HOLDOFF
					debounce_button = lcd.LEFT
				if ((buttons >> lcd.SELECT) & 1):
					state = STATE_HOLDOFF
					debounce_button = lcd.SELECT

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
		print("LCD Driver Crashed!")
	return

print('Initializing hardware and drivers..')

# Initialize the LCD
lcd = LCD.Adafruit_CharLCDPlate()
lcd.begin(16,2)
atexit.register(lcd.stop)

# Add the volume indicators
lcd.createChar(1,[0,0,0,0,0,0,0,30])
lcd.createChar(2,[0,0,0,0,0,0,16,30])
lcd.createChar(3,[0,0,0,0,8,8,16+8,30])
lcd.createChar(4,[0,0,4,4,8+4,8+4,16+8+4,30])
lcd.createChar(5,[2,2,4+2,4+2,8+4+2,8+4+2,16+8+4+2,30])

# Clear the screen
lcd.clear()
# Turn on the backlight
lcd.backlight(lcd.ON)
screen = True
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

# At this point, we need to catch the ^C to ensure we clean up gracefully.
try:
	print 'Connected. Initializing player...'
	# Mark that our last ping was now so we don't immediately ping.
	last_ping = time.clock()
	last_song_id = -1
	song = False

	client.send_status() # Loop needs an initial request to work.
	print 'Initialization finished. Player active!'
	print 'Press Ctrl-C to quit.'

	# --------------------------
	#        Main Loop
	# --------------------------
	while True:
		stats = client.fetch_status() # Get the results of the last request
		
		# If we've got anything to do from the LCD panel.
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
			elif action == ACTION_SCREEN_TOGGLE:
				if screen:
					screen = False
					lcd.backlight(lcd.OFF)
				else:
					screen = True
					lcd.backlight(lcd.ON)
			else:
				print('Unexpected action queue item: {0}'.format(action))
	
		# If he haven't pinged in a while, do so as a keepalive.
		if time.clock()-last_ping > 5:
			client.ping()
			last_ping = time.clock()			
	
		# If we can update the display
		if 'songid' in stats:
			# Lock the text so we can change it
			text_lock.acquire()
			# Check if it's a new song
			if stats['songid'] != last_song_id:
				# Build the new title based on the new song
				song = client.currentsong()
				last_song_id = song['id']
				title_string = "{0} [{1}] ".format(song.get('title',"No Title"), song.get('artist',"No Artist"))
				title_string = title_string.ljust(16)
				# Tell the LCD to reset the offset to 0 to show the new title.
				reset_event.set()
			text_lock.release()
		elif stats['state'] == "stop" and title_string != "               ":
			text_lock.acquire()
			title_string = "                "
			text_lock.release()
		# If we can tell when we are
		if 'elapsed' in stats:
			# Get the normal form of the time
			minutes = int(float(stats['elapsed'])/60)
			seconds = int(math.fmod(float(stats['elapsed']),60.0))
			elapsed = "{:3d}:{:02d}".format(minutes,seconds)
		else:
			elapsed = "---:--"

		# Get the volume and select the character that matches
		volchar = int(float(stats['volume'])/100*4)+1
		if volchar<1:
			volchar = 1
		if volchar > 5:
			volchar = 5

		

		# then build the second line
		if stats['state']=="pause":
			status_text = "Pause"
		elif stats['state']=="stop":
			status_text = "Stop"
		elif stats['state']=="play":
			status_text = "Play"
		else:
			status_text = "Unknown"

		# Lock the LCD text while we update the second line.
		text_lock.acquire()
		line2 = "{:>6s}{:^9s}{:1s}".format(elapsed,status_text,chr(volchar))
		# Let go of the text so the LCD can use it.
		text_lock.release()

		# Tell the server to start working on getting us the status while we go back to sleep
		client.send_status()
		# Nap time!
		time.sleep(.5)

except KeyboardInterrupt:
	pass #from here on out we're bailing

print "Disconnecting..."
running = False # Tell the LCD thread we're done
client.disconnect()
print "Shutting down plate_watcher..."
plate_watcher.join() # Wait for the LCD thread to die
print "Cleaning up LCD..."
lcd.backlight(lcd.OFF) # Turn off the backlight
lcd.clear() # And clear the screen
print "Bye!"

