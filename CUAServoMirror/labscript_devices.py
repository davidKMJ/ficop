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

from labscript import IntermediateDevice, AnalogOut, DigitalOut, Trigger
from labscript.labscript import Device, set_passed_properties
import numpy as np

class CUAServoMirror(IntermediateDevice):

    # A human readable name for device model used in error messages
    description = "Mirror Servo Control"
    # The labscript Output classes this device supports
    allowed_children = [ ]
    # The maximum update rate of this device (in Hz)
    clock_limit = 1e4

    @set_passed_properties(
        property_names={
            'connection_table_properties':
                [
                    'name',
                    'mirror_mapping_dict',
                    'com_port',
                    'baud_rate',
                ]
        }
    )
    def __init__ (self, name, mirror_mapping_dict, com_port, baud_rate= 1000000, **kwargs):
        """init the mirror controller

        Args:
            name (str): name of mirror controller
            mirror_mapping_dict (dict): In the format of {name_of_mirror:(horizontal_servo_id, vertical_servo_id)}
            com_port (str): com port for the mirror controller
            baud_rate (int, optional): rate at which to communicate with the mirror controller. Defaults to 500000.
        """
        IntermediateDevice.__init__ ( self , name , parent_device=None, **kwargs)
        self.BLACS_connection = "Mirror controller {}, BAUD: {}".format(com_port , str(baud_rate))
        self.name = name
        self.mirror_mapping_dict = mirror_mapping_dict
        # the maximum integer value the motor can turn to
        self.max_value = 63487

        self.mirror_positions_dict = {}
        for key in self.mirror_mapping_dict:
            self.mirror_positions_dict[key] = (None, None)


    def generate_code(self,hdf5_file):
        """Write the frequency sequence for each channel to the HDF file

        Args:
            hdf5_file (hdf): labscript hdf file
        """

        Device.generate_code(self, hdf5_file)

        grp = hdf5_file.require_group(f'/devices/{self.name}/')

        for mirror_name in self.mirror_positions_dict.keys():
            if self.mirror_positions_dict[mirror_name][0] is not None and self.mirror_positions_dict[mirror_name][1] is not None:
                positions = grp.require_dataset(mirror_name, (2,), dtype='i')
                positions[:] = self.mirror_positions_dict[mirror_name]
        


    def set_position(self, mirror_name, horizontal_position, vertical_position):
        """Set the position for the given mirror

        Args:
            mirror_name (str): name of the mirror
            horizontal_position (int): int position of the mirror
            vertical_position (int): vertical position of the mirror to set
        """

        # if not 0 <= horizontal_position <= self.max_value:
        #     # raise(ValueError("The maximum horizontal value is {}, but {} was entered".format(self.max_value, horizontal_position)))
        #     horizontal_position = np.clip(horizontal_position, 0, self.max_value)
        # if not 0 <= vertical_position <= self.max_value:
        #     # raise(ValueError("The maximum vertical value is {}, but {} was entered".format(self.max_value, vertical_position)))
        #     vertical_position = min(vertical_position, self.max_value)
        #     vertical_position = max(vertical_position, 0)


        self.mirror_positions_dict[mirror_name] = (horizontal_position, vertical_position)