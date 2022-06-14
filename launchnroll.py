#!/usr/bin/env python

##########################################################################################################################################

import os, sys, getopt
from mididings import *
from mididings.event import *
from mididings.util import *
#from mido import MetaMessage
#from mido import MidiFile
#import subprocess
#import json
import hjson
from pathlib import Path
#from plyer import notification
#import desktop_notify
from PyQt5.QtWidgets import QApplication, QLabel
# for debugging:
import binascii
from colorama import Fore
from colorama import Style


# Reading config file ####################################################################################################################

# json = JsonComment(json)
configfile = Path(os.path.realpath(os.path.join(os.path.dirname(__file__), 'launchnroll-config.json')))
#lnrconfig = json.loadf(configfile) # , default = {"Config": {"Templates": False}}
configfilehandler = open(configfile, "r")
configcontent = configfilehandler.read()
configfilehandler.close()
lnrconfig = hjson.loads(configcontent)

# Get Midi Output devices from config (for lookups)
lnrconfig_out_ports = []
for ut in lnrconfig["Config"]["Templates"]["User"]:
	lnrconfig_out_ports.append(ut["Output Device"])
for ft in lnrconfig["Config"]["Templates"]["Factory"]:
	lnrconfig_out_ports.append(ft["Output Device"])
lnrconfig_out_ports.append(lnrconfig["Config"]["Options"]["Input Devices"][0]["Output Device"]) # Adding the controller too for LED setting. TODO: multiple controllers
lnrconfig_out_ports = list(set(lnrconfig_out_ports))
lnrconfig_out_ports_dict = dict()
for i, item in enumerate(lnrconfig_out_ports):
	outport_name = "Out"+str(i)+" (to "+item.replace(".*","",1)+")"
	lnrconfig_out_ports[i] = (outport_name, item)
	lnrconfig_out_ports_dict[item] = outport_name
	
# Get knob and button indices from config (for lookups)
lnrconfig_in_knobs = [None] * 128
for i, knob in enumerate(lnrconfig["Config"]["Options"]["Input Devices"][0]["Factory Templates"][0]["Knobs"]):
	lnrconfig_in_knobs[knob["CC Number"]] = i
lnrconfig_in_buttons = [None] * 128
for i, button in enumerate(lnrconfig["Config"]["Options"]["Input Devices"][0]["Factory Templates"][0]["Buttons"]):
	lnrconfig_in_buttons[button["Note Number"]] = i

# Get default template (Factory Template 1) from config	
current_template = lnrconfig["Config"]["Templates"]["Factory"][0]
current_template_number = 8
current_knob = None
current_button = None
current_button_number = None


# Mididings configuration ################################################################################################################

config(
    backend = 'alsa',
    client_name = 'LaunchNRoll',
    in_ports = [("In1", lnrconfig["Config"]["Options"]["Input Devices"][0]["Input Device"])], # Only one input device is supported now
    out_ports = lnrconfig_out_ports,
	data_offset = 1 # port and channel numbers are in the range 1-128
)

# Startup ################################################################################################################################

print("LaunchNRoll listening to "+(lnrconfig["Config"]["Options"]["Input Devices"][0]["Input Device"]).replace(".*","",1))


# Helper functions #######################################################################################################################

# Flatten a list
#def flatten_list(t):
#	flat_list = []
#	for sublist in t:
#		for item in sublist:
#			flat_list.append(item)
#	return flat_list

# Scale conversion, (implying that input is always 0-127)
def scale_convert(invalue, out_min, out_max):
	outvalue = ((float(invalue) / 127) * (out_max - out_min)) + out_min # ((float(X - A) / (B - A)) * (D - C)) + C
	return int(round(outvalue))

def format_2bytes(in_value):
	out_lsb = format((in_value % 127), '02x')
	out_msb = format((in_value // 127), '02x')
	out_value = out_msb+" "+out_lsb
	return out_value

# Sysex bulk dump checksum ('data' is the sysex data minus the 6 byte sysex header)
def _create_checksum(data):
	cs = sum(ord(c) for c in data)
	return ((cs & 0x7f) ^ 0x7f) + 1

# Cycle through range of values
def cycle_range(current_value, delta_value, range_min, range_max):
	return ((current_value-range_min+delta_value)%(range_max-range_min+1))+range_min

# Get child value or return default
def getchild_or_default(parent_obj, child_id, default_value):
	if child_id in parent_obj:
		return parent_obj[child_id]
	else:
		return default_value

# Selected value for display
def selected_value(current_button, sel_value):
	return_string = ""
	min_value = getchild_or_default(current_button, "Output Min Value", 0)
	try:
		for i, val in enumerate(current_button["Output Values"]):
			if i==(sel_value-min_value):
				return_string += "\033[1m"+"["+str(val)+"]|"+"\033[0m"
			else:
				return_string += " "+str(val)+" |"
	except KeyError:
		return_string = str(sel_value)
	return return_string

# Set one LED light for given "factory" template (returns event)
def set_led_light(template, template_number, knoborbutton_type, knoborbutton_index, color_string=None, brightness_value=0, eventout=False):
	input_device = lnrconfig["Config"]["Options"]["Input Devices"][0]
	out_template = format(template_number, '02x')
	try:
		out_index = format(lnrconfig["Config"]["Options"]["Input Devices"][0]["Factory Templates"][0][knoborbutton_type][knoborbutton_index]["LED ID"], '02x')
		if color_string is not None:
			brightness_values = input_device["LED Change"]["Colors"][color_string]
		elif "LED Color" in template[knoborbutton_type][knoborbutton_index]:
			brightness_values = input_device["LED Change"]["Colors"][template[knoborbutton_type][knoborbutton_index]["LED Color"]]
		elif "Off" in input_device["LED Change"]["Colors"]:
			brightness_values = input_device["LED Change"]["Colors"]["Off"]
		else:
			return None
		out_value = brightness_values[brightness_value] if brightness_value < len(brightness_values) and brightness_values[brightness_value] is not None else brightness_values[0]
	except (KeyError, IndexError):
		return None
	# TODO: handle other output types too
	# DEBUG: print("LED "+knoborbutton_type+" "+str(knoborbutton_index))
	if eventout==True:
		return_event = SysExEvent(lnrconfig_out_ports_dict[input_device["Output Device"]],
							 bytes.fromhex(input_device["LED Change"]["Sysex String"].replace("tt", out_template, 1).replace("ii", out_index, 1).replace("vv", out_value, 1)))
	else:
		return_event = SysEx(lnrconfig_out_ports_dict[input_device["Output Device"]],
							 bytes.fromhex(input_device["LED Change"]["Sysex String"].replace("tt", out_template, 1).replace("ii", out_index, 1).replace("vv", out_value, 1)))
	return return_event

# Set all LED lights for given "factory" template (returns list of events)
def set_all_led_lights(template, template_number, brightness_value=0, eventout=False):
	return_list = []
	for i, knob in enumerate(template["Knobs"]):
		color_string = getchild_or_default(knob, "LED Color", "Off")
		return_list.append(set_led_light(template, template_number, "Knobs", i, color_string, 1, eventout))
	for i, button in enumerate(template["Buttons"]):
		color_string = getchild_or_default(button, "LED Color", "Off")
		return_list.append(set_led_light(template, template_number, "Buttons", i, color_string, brightness_value, eventout))
	return_list = list(filter(None, return_list)) # list(filter(lambda x:isinstance(x, list) or x is None, return_list))
	return return_list

# Send init messages that are defined in the template
def send_init_messages(template):
	return_list = []
	input_device = lnrconfig["Config"]["Options"]["Input Devices"][0]
	for i, message in enumerate(current_template["Send Init"]):
		return_list.append(SysEx(lnrconfig_out_ports_dict[input_device["Output Device"]],
							 bytes.fromhex(message)))

		
# Handle input ###########################################################################################################################

def process_events(event): # '\xf0\x07\x15\x42'
	global current_template
	global current_template_number
	global current_button
	global current_button_number
	global current_knob
	return_event = None
	if event.type == CTRL:
		try:
			current_knob = current_template["Knobs"][lnrconfig_in_knobs[event.ctrl]]
		except IndexError:
				print("Knob "+str(lnrconfig_in_knobs[event.ctrl])+" (CC Number: "+str(event.ctrl)+") is not configured")
				return None
		out_min = getchild_or_default(current_knob, "Output Min Value", 0)
		out_max = getchild_or_default(current_knob, "Output Max Value", 127)
		old_value = getchild_or_default(current_knob, "Last Value", out_min)
		new_value = scale_convert(event.value, out_min, out_max)
		if current_knob["Output Type"]=="Sysex":
			# TODO: Handle other output types too
			# TODO: Catch current value
			if new_value!=old_value:
				out_value = format_2bytes(new_value) if out_max > 127 else format(new_value, '02x')
				print(out_value)
				return_event = SysExEvent(lnrconfig_out_ports_dict[current_template["Output Device"]],
										  bytes.fromhex(current_knob["Sysex String"].replace("vv", out_value, 1)))
				current_knob["Last Value"] = new_value
		elif (current_knob["Output Type"] in ["Increment", "Decrement"]) and event.value==127 and current_button is not None: # TODO: Or current knob, but not itself
			# TODO: Handle other output types too
			print(current_knob["Control Name"])
			out_min = getchild_or_default(current_button, "Output Min Value", 0)
			out_max = getchild_or_default(current_button, "Output Max Value", 127)
			old_value = getchild_or_default(current_button, "Last Value", out_min)
			delta_value = 1 if current_knob["Output Type"]=="Increment" else -1
			new_value = cycle_range(old_value, delta_value, out_min, out_max)
			out_value = format(new_value, '02x')
			return_event = SysExEvent(lnrconfig_out_ports_dict[current_template["Output Device"]],
									  bytes.fromhex(current_button["Sysex String"].replace("vv", out_value, 1)))
			current_button["Last Value"] = new_value
			print(current_button["Control Name"]+": "+selected_value(current_button, new_value), end="\r") # "\x1b[1K\r"
		return return_event
	elif event.type == NOTEON:
		return_event = []
		if current_button_number != event.note: # First push of button
			if current_button_number is not None:
				colorstr = getchild_or_default(current_button, "LED Color", None)
				return_event.append(set_led_light(current_template, current_template_number, "Buttons", lnrconfig_in_buttons[current_button_number], color_string=colorstr, brightness_value=0, eventout=True))
			current_button_number = event.note # This will NOT change if a "Multiple" type button is selected
			current_button = current_template["Buttons"][lnrconfig_in_buttons[current_button_number]] # This WILL change if a "Multiple" type button is selected
			if current_button["Output Type"]=="Multiple":
				try:
					current_button = current_button["Buttons"][current_button["Current SubButton Index"]]
				except KeyError:
					current_button["Current SubButton Index"] = 0
					current_button = current_button["Buttons"][0]
		else: # Repeated push of button
			if current_template["Buttons"][lnrconfig_in_buttons[current_button_number]]["Output Type"]=="Multiple":
				current_subbutton_index = current_template["Buttons"][lnrconfig_in_buttons[current_button_number]]["Current SubButton Index"]
				new_subbutton_index = cycle_range(current_subbutton_index, 1, 0, (len(current_template["Buttons"][lnrconfig_in_buttons[current_button_number]]["Buttons"])-1))
				current_button = current_template["Buttons"][lnrconfig_in_buttons[current_button_number]]["Buttons"][new_subbutton_index]
				current_template["Buttons"][lnrconfig_in_buttons[current_button_number]]["Current SubButton Index"] = new_subbutton_index
			# TODO: If not Multiple (and config allows?) increment value
		out_min = getchild_or_default(current_button, "Output Min Value", 0)
		old_value = getchild_or_default(current_button, "Last Value", out_min)
		try:
			print("\n"+current_button["Control Name"]+": "+selected_value(current_button, old_value), end="\r")
		except KeyError:
			print("Button "+str(lnrconfig_in_buttons[current_button_number])+" is not fully configured")
		# return_event = set_all_led_lights(current_template, current_template_number, brightness_value=0, eventout=True)
		colorstr = getchild_or_default(current_button, "LED Color", None)
		return_event.append(set_led_light(current_template, current_template_number, "Buttons", lnrconfig_in_buttons[current_button_number], color_string=colorstr, brightness_value=1, eventout=True))
		return_event = list(filter(None, return_event))
		return return_event
	elif event.type == SYSEX and event.sysex[0:7]==bytearray(b'\xF0\x00\x20\x29\x02\x11\x77'): # Incoming template change
		# TODO: Handle other template change types too (using config)
		current_template_number = event.sysex[7]
		if current_template_number<8:
			try:
				current_template = lnrconfig["Config"]["Templates"]["User"][current_template_number]
				print("User Template "+str(current_template_number+1))
				#notify = desktop_notify.glib.Notify('summary', "User Template "+str(current_template_number+1))
				#notify.show_async()
			except IndexError:
				print("User Template "+str(current_template_number+1)+" is not configured")
		elif current_template_number>7:
			try:
				current_template = lnrconfig["Config"]["Templates"]["Factory"][current_template_number-8]
				print("Factory Template "+str(current_template_number-7))
				#notify = desktop_notify.glib.Notify('summary', "User Template "+str(current_template_number-7))
				#notify.show_async()
			except IndexError:
				print("Factory Template "+str(current_template_number-7)+" is not configured")
		return None
	return event


# Initialize controller ##################################################################################################################

start_controller = [set_all_led_lights(current_template, current_template_number, brightness_value=0)] #,
					# send_init_messages(current_template)]


# Deinitialize controller ################################################################################################################

stop_controller = []


# Main mididings loop ####################################################################################################################

run(Fork([
        Init(start_controller),
        Filter(SYSEX|NOTE|CTRL) >> Process(process_events),
        Exit(stop_controller)
    ]))


# Exit ###################################################################################################################################

print('\nBye!\n')
