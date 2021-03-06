import json
import copy
import uuid

import config

####################################################
####				HELPER FUNCTIONS			####
####################################################

def load_json_from_file(filename):
	f = open(filename)
	data = json.load(f)
	f.close()

	return data

def store_json_to_file(data, filename):
	f = open(filename, 'w')
	json.dump(data, f, indent=4)
	f.close()

def decode_shape(s, separators=['#@$', '^^', '~']):
	if not len(separators):
		return s

	result = list()

	for sub in s.split(separators[0]):
		result.append(decode_shape(sub, separators[1:]))

	return result

def encode_shape(l, separators=['#@$', '^^', '~']):
	if not len(separators):
		return l

	result = [encode_shape(x, separators[1:]) for x in l]

	return separators[0].join(result)

def shape_to_str(i, subs):
	result = 'Shape %d\n' % i
	for x, sub in enumerate(subs):
		result += '    Sub %d\n' % x
		for y, subsub in enumerate(sub):
			result += '        Subsub %d\n' % y
			for z, field in enumerate(subsub):
				result += '            %d: %s\n' % (z, field)
	return result

def dump_shapes(data, filename):
	f = open(filename, 'w')
	for i, shape in enumerate(data):
		subs = decode_shape(shape)
		f.write(shape_to_str(i, subs))
	f.close()

def offset_x_y(s, x, y, separator=' '):
	data = s.split(separator)

	b_ord = False
	skip = 0
	for i, val in enumerate(data):
		if val == 'A':
			skip = 5
		elif skip > 0:
			skip -= 1
		else:
			try:
				f_val = float(val)
				f_val += y if b_ord else x
				data[i] = str(f_val)
				b_ord = not b_ord
			except ValueError:
				pass

	return separator.join(data)

def find_sub(subs, values):
	for sub in subs:
		for key, val in values.items():
			if sub[0][key] != val:
				break
		else:
			# OK, match
			return sub

	# Did not found
	return None

def translate_channel_prefix(oldPrefix, ch_id):
	if oldPrefix.startswith('G:'):
		# Treat names that start with G: as global nets. Here we don't add a channel
		# name, but remove the G: prefix so it ties in with the global net in the main
		# pcb or schematic. This is useful for address busses, databusses. clock lines,
		# etc.. -TVe
		return oldPrefix[2:]
	elif config.channel_prefix_style == 1:
		return oldPrefix + '_' + ch_id
	elif config.channel_prefix_style == 2:
		return ch_id + ':' + oldPrefix
	else:
		raise Exception('Unknown channel prefix style, please check configuration: ' + config.channel_prefix_style)

####################################################
####				MAIN ROUTINE				####
####################################################

# Load schematics and PCBs
main_sch = load_json_from_file(config.main_sch_file)
main_pcb = load_json_from_file(config.main_pcb_file)

for ch_sch_file, ch_pcb_file, channels in config.channel_sources:
	# Load channel schematics and PCBs
	ch_sch = load_json_from_file(ch_sch_file)
	ch_pcb = load_json_from_file(ch_pcb_file)

	# TODO: checks
	if len(ch_sch['schematics']) != 1:
		print('ERROR: Channel schematic shall contain exactly 1 sheet')
		exit(1)

	# Dump shapes in text form (for debug purpose)
	# dump_shapes(ch_sch['schematics'][0]['dataStr']['shape'], 'sch_shapes.txt')
	# dump_shapes(ch_pcb['shape'], 'pcb_shapes.txt')

	for i_ch, (ch_x, ch_y) in channels.items():
		####################################################
		####			PROCESSING SCHEMATIC			####
		####################################################

		# Create deepcopy of channel schematic sheet
		sch = copy.deepcopy(ch_sch['schematics'][0])

		# Prepare empty dictionary for part sch-to-pcb matching
		part_dict = dict()
		net_dict = dict()

		# Generate new UUID of schematic sheet
		sch['dataStr']['head']['uuid'] = uuid.uuid4().hex

		# Append channel name to the sheet title
		if config.channel_prefix_style == 1:
			sch['title'] += '_' + str(i_ch)
		elif config.channel_prefix_style == 2:
			sch['title'] = str(i_ch) + ':' + sch['title']
		else:
			raise Exception('Unknown channel prefix style, please check configuration: ' + config.channel_prefix_style)

		# Process shapes
		shape_list = sch['dataStr']['shape']

		for i, shape in enumerate(shape_list):
			# Split subshapes
			subs = decode_shape(shape)

			# Process shape
			shape_type = subs[0][0][0]

			# Process parts
			if shape_type == 'LIB':
				# Find prefix sub
				prefix_sub = find_sub(subs, {0: 'T', 1: 'P'})

				# Ensure sub 2 is a prefix text
				if prefix_sub is None:
					print('ERROR: Prefix text of SCH LIB shape is not recognized')
					print(shape_to_str(i, subs))
					continue

				# Get old prefix and unique identifier
				prefix_old = prefix_sub[0][12]
				old_id = subs[0][0][6]

				# Update part, excluding sheet frame
				if not old_id.startswith('frame_lib'):
					# Append channel to the prefix
					prefix_new = translate_channel_prefix(prefix_old, str(i_ch))

					# Replace unique identifier, store reference in the dictionary
					new_id = 'gge' + uuid.uuid4().hex[-16:]
					part_dict[old_id] = new_id
					subs[0][0][6] = new_id

					# Generate pad nets
					for sub in subs:
						if sub[0][0] == 'P':
							pad_name = sub[4][4]
							pad_net_old = '%s_%s' % (prefix_old, pad_name)
							pad_net_new = '%s_%s' % (prefix_new, pad_name)
							net_dict[pad_net_old] = pad_net_new

					# Store new prefix
					prefix_sub[0][12] = prefix_new

			# Process net labels
			elif shape_type == 'N':
				# Get old net name, append channel to the new name
				net_name_old = subs[0][0][5]
				net_name_new = translate_channel_prefix(net_name_old, str(i_ch))

				# Store net
				net_dict[net_name_old] = net_name_new

				# Store new net name
				subs[0][0][5] = net_name_new

			# Process net ports
			elif shape_type == 'F' and subs[0][0][1] == 'part_netLabel_netPort':
				# Get old net name, append channel to the new name
				net_name_old = subs[0][2][0]
				net_name_new = translate_channel_prefix(net_name_old, str(i_ch))

				# Store net
				net_dict[net_name_old] = net_name_new

				# Store new net name
				subs[0][2][0] = net_name_new

			# All power and ground netlabels are treated as global nets
			elif shape_type == 'F':
				net_name = subs[0][2][0]
				net_dict[net_name] = net_name

			# Reassemble shape
			shape_list[i] = encode_shape(subs)

		# Add processed schematic sheet to the main project
		main_sch['schematics'].append(sch)

		print('Schematic components: %d' % len(part_dict))
		print('Schematic nets: %d' % len(net_dict))
		# print(json.dumps(net_dict, indent=4))

		####################################################
		####				PROCESSING PCB				####
		####################################################

		shape_list = ch_pcb['shape']

		# Process shapes
		for i, shape in enumerate(shape_list):
			# Split subshapes
			subs = decode_shape(shape)

			# Update parts
			shape_type = subs[0][0][0]

			if shape_type == 'LIB':
				# Find prefix sub
				prefix_sub = find_sub(subs, {0: 'TEXT', 1: 'P'})

				# Ensure sub 2 is a prefix text
				if prefix_sub is None:
					print('ERROR: Prefix text of PCB LIB shape is not recognized')
					print(shape_to_str(i, subs))
				else:
					# Append channel to the prefix
					prefix_sub[0][10] = translate_channel_prefix(prefix_sub[0][10], str(i_ch))
					# Field 11 is assumed to be line data that draws the text.
					# Remove it to force EasyEDA to recreate it. -TVe
					prefix_sub[0][11] = ''

				# Replace unique identifier
				old_id = subs[0][0][6]
				if old_id in part_dict.keys():
					subs[0][0][6] = part_dict[old_id]
					del part_dict[old_id]
				else:
					print('WARNING: PCB component %s is not matched with any schematic component' % subs[2][0][12])

			# Process coordinates and nets of all subshapes equally
			for sub in subs:
				# Ensure there are no subsubs
				if len(sub) != 1:
					print('ERROR: Unsupported pcb shape structure')
					print(shape_to_str(i, subs))

				# Further processing is only around sub[0]
				data = sub[0]
				shape_type = data[0]

				if shape_type == 'LIB':
					data[1] = str(float(data[1]) + ch_x)
					data[2] = str(float(data[2]) + ch_y)

				elif shape_type == 'COPPERAREA' or shape_type == 'TRACK':
					data[4] = offset_x_y(data[4], ch_x, ch_y)

					# update net data[3]
					net_name = data[3]
					if net_name:
						try:
							data[3] = net_dict[net_name]
						except KeyError:
							print('WARNING: PCB net %s is not matched with any schematic net' % net_name)

				elif shape_type == 'SOLIDREGION':
					data[3] = offset_x_y(data[3], ch_x, ch_y)

				elif shape_type == 'ARC':
					data[4] = offset_x_y(data[4], ch_x, ch_y)

				elif shape_type == 'TEXT':
					data[2] = str(float(data[2]) + ch_x)
					data[3] = str(float(data[3]) + ch_y)

					data[11] = offset_x_y(data[11], ch_x, ch_y)

				elif shape_type == 'VIA':
					data[1] = str(float(data[1]) + ch_x)
					data[2] = str(float(data[2]) + ch_y)

					# update net data[4]
					net_name = data[4]
					if net_name:
						try:
							data[4] = net_dict[net_name]
						except KeyError:
							print('WARNING: PCB net %s is not matched with any schematic net' % net_name)

				elif shape_type == 'PAD':
					data[2] = str(float(data[2]) + ch_x)
					data[3] = str(float(data[3]) + ch_y)

					data[10] = offset_x_y(data[10], ch_x, ch_y)
					data[19] = offset_x_y(data[19], ch_x, ch_y, separator=',')

					# update net data[7]
					net_name = data[7]
					if net_name:
						try:
							data[7] = net_dict[net_name]
						except KeyError:
							print('WARNING: PCB net %s is not matched with any schematic net' % net_name)

				elif shape_type == 'CIRCLE' or shape_type == 'HOLE':
					data[1] = str(float(data[1]) + ch_x)
					data[2] = str(float(data[2]) + ch_y)

				elif shape_type == 'SVGNODE':
					# svg_data = json.loads(data[1])
					print("NOTE: PCB shape SVGNODE has been skipped (not implemented yet)")

				else:
					print('ERROR: Unsupported pcb subshape %s' % shape_type)
					for z, field in enumerate(data):
						print('            %d: %s' % (z, field))

			# Reassemble shape and add to the main pcb
			main_pcb['shape'].append(encode_shape(subs))

		# Print info
		if len(part_dict) > 0:
			print('WARNING: Unmatched schematic components:', list(part_dict.keys()))

####################################################
####				FINALIZE JOB				####
####################################################

# Store resulting schematic and PCB
store_json_to_file(main_sch, config.out_sch_file)
store_json_to_file(main_pcb, config.out_pcb_file)
