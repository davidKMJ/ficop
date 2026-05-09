#####################################################################
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

from collections import defaultdict
import time

import labscript_utils.h5_lock  # Must be imported before importing h5py.
import h5py
import numpy as np
from labscript.labscript import set_passed_properties
from blacs.tab_base_classes import Worker

from .scservo_sdk import *                    # Uses SCServo SDK library

def encoder(x):
    '''goes from -32767 to 32767 to 0 to 65534'''
    #clip the value to the range
    x = np.clip(x, -32000, 32000)

    if x >= 0 and x <= 32767:
        return x
    elif x < 0 and x >= -32767:
        return (-x + 32767)

def decoder(x):
    '''goes from 0 to 65534 to -32767 to 32767'''
    #clip the value to the range
    x = np.clip(x, 0, 65534)
    
    if x >= 0 and x <= 32767:
        return x
    elif x > 32767 and x <= 65534:
        return (-x + 32767)

class CUAServoMirrorWorker(Worker):

    def init (self):
        # Once off device initialisation code called when the
        # worker process is first started .
        # Usually this is used to create the connection to the
        # device and/or instantiate the API from the device
        # manufacturer
        # Initialize PortHandler instance
        # Set the port path
        # Get methods and members of PortHandlerLinux or PortHandlerWindows

        # List of register values for the controller
        self.register_dict = {
            'ADDR_SCS_TORQUE_ENABLE'     : 40,
            'ADDR_SCS_GOAL_ACC'          : 41,
            'ADDR_SCS_GOAL_POSITION'     : 42,
            'ADDR_SCS_GOAL_SPEED'        : 46,
            'ADDR_SCS_PRESENT_POSITION'  : 56,
            'SCS_MOVING_STATUS_THRESHOLD': 20,
            }
        self.last_position_horizontal = None
        self.last_position_vertical = None
        self.port_handler = PortHandler(self.com_port)

        # Initialize PacketHandler instance
        # Get methods and members of Protocol
        protocol_end                = 0                 # SCServo bit end(STS/SMS=0, SCS=1)
        self.packet_handler = PacketHandler(protocol_end)

        # used when need to synchronously move both mirrors and read
        # # Initialize GroupSyncWrite instance
        # self.group_sync_write = GroupSyncWrite(self.port_handler, self.packet_handler, ADDR_STS_GOAL_POSITION, 2)

        # # Initialize GroupSyncRead instace for Present Position
        # self.group_sync_read = GroupSyncRead(self.port_handler, self.packet_handler, ADDR_STS_PRESENT_POSITION, 4)

        # Open port
        if self.port_handler.openPort():
            print("Succeeded in opening the port")
        else:
            print("Failed to open the port")
            raise(RuntimeError("Failed to connect {}".format(self.name)))


        # Set port baudrate
        if self.port_handler.setBaudRate(self.baud_rate):
            print("Succeeded in changing the baudrate")
        else:
            print("Failed in changing the baudrate")
            raise(RuntimeError("Failed to initialize baud rate {}".format(self.name)))

        # Set the speeds
        for mirror_name in self.mirror_mapping_dict:
            horizontal_id = self.mirror_mapping_dict[mirror_name][0]
            vertical_id = self.mirror_mapping_dict[mirror_name][1]
            # Write SCServo speed for h mirror. "0" is the speed written, not sure what kind of units or whatever it is
            scs_comm_result, scs_error = self.packet_handler.write2ByteTxRx(self.port_handler, horizontal_id, 
                                                                      self.register_dict['ADDR_SCS_GOAL_SPEED'], 
                                                                      0)
            self.check_error(scs_comm_result, scs_error)

            # Write SCServo speed for v mirror
            scs_comm_result, scs_error = self.packet_handler.write2ByteTxRx(self.port_handler, vertical_id, 
                                                                      self.register_dict['ADDR_SCS_GOAL_SPEED'], 
                                                                      0)
            self.check_error(scs_comm_result, scs_error)

    def check_error(self, scs_comm_result, scs_error):
        """Check the results of sending bytes to the controller

        """
        if scs_comm_result != COMM_SUCCESS:
            print("%s" % self.packet_handler.getTxRxResult(scs_comm_result))
        elif scs_error != 0:
            print("%s" % self.packet_handler.getRxPacketError(scs_error))


    def set_position(self, mirror_name, horizontal_position, vertical_position, fresh=True):
        """Set the position for both the horizontal and the vertical mirror 

        Args:
            mirror_name ([str]): name of the mirror to be moved
            horizontal_position ([int]): integer final value for the horizontal mirror position
            vertical_position ([int]): integral final value for the vertical mirror position
        """
        
        #clip the values to the limits
        max_value = 65000
        min_value = -max_value
        horizontal_position = encoder(horizontal_position)
        vertical_position = encoder(vertical_position)

        # checked to see if we should reupload
        if fresh or self.last_position_horizontal != horizontal_position or self.last_position_vertical != vertical_position:

            horizontal_id = self.mirror_mapping_dict[mirror_name][0]
            vertical_id = self.mirror_mapping_dict[mirror_name][1]
            print("Setting mirror position for {} to ({},{})".format(mirror_name, horizontal_position, vertical_position))

            # Write SCServo goal position for horizontal mirror
            scs_comm_result, scs_error = self.packet_handler.write2ByteTxRx(self.port_handler, horizontal_id, 
                                                                            self.register_dict['ADDR_SCS_GOAL_POSITION'], 
                                                                            horizontal_position)
            self.check_error(scs_comm_result, scs_error)

            # Write SCServo goal position
            scs_comm_result, scs_error = self.packet_handler.write2ByteTxRx(self.port_handler, vertical_id, 
                                                                            self.register_dict['ADDR_SCS_GOAL_POSITION'], 
                                                                            vertical_position)
            self.check_error(scs_comm_result, scs_error)

            self.last_position_horizontal = horizontal_position
            self.last_position_vertical = vertical_position

            return_message = (horizontal_position, vertical_position)

        else:
            print(f"Used smart programming; didn't move.")
            return_message = None

        return return_message



    def get_position(self, mirror_name):
        """Get the position for both the horizontal and the vertical mirror 

        Args:
            mirror_name ([str]): name of the mirror to be moved

        """
        horizontal_id = self.mirror_mapping_dict[mirror_name][0]
        vertical_id = self.mirror_mapping_dict[mirror_name][1]
        # Read SCServo present position. The speed and the position are in the same response
        scs_present_position_speed, scs_comm_result, scs_error = self.packet_handler.read4ByteTxRx(self.port_handler, 
                                                                                                    horizontal_id, 
                                                                                                    self.register_dict['ADDR_SCS_PRESENT_POSITION'])
        self.check_error(scs_comm_result, scs_error)

        # extract the horizontal position and the speed. (We don't care about the speed as of writing this)
        horizontal_position = SCS_LOWORD(scs_present_position_speed)
        horizontal_present_speed = SCS_HIWORD(scs_present_position_speed)

        # do the same for the vertical
        scs_present_position_speed, scs_comm_result, scs_error = self.packet_handler.read4ByteTxRx(self.port_handler, 
                                                                                                    vertical_id, 
                                                                                                    self.register_dict['ADDR_SCS_PRESENT_POSITION'])
        self.check_error(scs_comm_result, scs_error)

        vertical_position = SCS_LOWORD(scs_present_position_speed)
        vertical_present_speed = SCS_HIWORD(scs_present_position_speed)
        
        horizontal_position = decoder(horizontal_position)
        vertical_position = decoder(vertical_position)

        return horizontal_position, vertical_position

    def toggle_torque(self, mirror_name, is_checked):
        """Enable or disable the ability to move the mirror by hand/move the motor

        Args:
            mirror_name (str): name of the mirror
            is_checked (bool): If true, torque is enabled and the mirror can not be moved by hand
                               If false, it can be moved by hand
        """     
        horizontal_id = self.mirror_mapping_dict[mirror_name][0]
        vertical_id = self.mirror_mapping_dict[mirror_name][1]

        if is_checked:
            torque_val = 1
        else:  
            torque_val = 0

        scs_comm_result, scs_error = self.packet_handler.write1ByteTxRx(self.port_handler, horizontal_id, 
                                                                        self.register_dict['ADDR_SCS_TORQUE_ENABLE'], torque_val)

        self.check_error(scs_comm_result, scs_error)

        scs_comm_result, scs_error = self.packet_handler.write1ByteTxRx(self.port_handler, vertical_id, 
                                                                        self.register_dict['ADDR_SCS_TORQUE_ENABLE'], torque_val)

        self.check_error(scs_comm_result, scs_error)

    def shutdown (self):
        # Once off device shutdown code called when the
        # BLACS exits
        self.port_handler.closePort()

    def program_manual ( self , front_panel_values ):
        # Update the output state of each channel using the values
        # in front_panel_values ( which takes the form of a
        # dictionary keyed by the channel names specified in the
        # BLACS GUI configuration
        # return a dictionary of coerced / quantised values for each
        # channel , keyed by the channel name (or an empty dictionary )
        return {}
        
    def transition_to_buffered ( self , device_name , h5_file_path,
    initial_values , fresh ):
        # Access the HDF5 file specified and program the table of
        # hardware instructions for this device .
        # Place the device in a state ready to receive a hardware
        # trigger (or software trigger for the master pseudoclock )
        #
        # The current front panel state is also passed in as
        # initial_values so that the device can ensure output
        # continuity up to the trigger .
        #
        # The fresh keyword indicates whether the entire table of
        # instructions should be reprogrammed (if the device supports
        # smart programming )
        # Return a dictionary , keyed by the channel names , of the
        # final output state of the shot file . This ensures BLACS can
        # maintain output continuity when we return to manual mode
        # after the shot completes .

        self.h5_filepath = h5_file_path
        self.device_name = device_name

        # From the H5 sequence file, get the sequence we want programmed into the arduino
        with h5py.File(h5_file_path, 'r') as hdf5_file:
            
            devices = hdf5_file['devices'][device_name]
            # Iterate over the set positions for the mirrors, add fresh
            for mirror_name in devices.keys():
                positions = devices[mirror_name]
                self.set_position(mirror_name, horizontal_position=positions[0], vertical_position=positions[1], fresh=fresh)

        final_values = {}
        return final_values


    def transition_to_manual ( self ):
        # Called when the shot has finished , the device should
        # be placed back into manual mode
        # return True on success
        return True

    def abort_transition_to_buffered ( self ):
        # Called only if transition_to_buffered succeeded and the
        # shot if aborted prior to the initial trigger
        # return True on success
        return True
    def abort_buffered ( self ):
        # Called if the shot is to be abort in the middle of
        # the execution of the shot ( after the initial trigger )
        # return True on success
        return True

