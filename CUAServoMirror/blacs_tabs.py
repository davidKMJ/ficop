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



from blacs.device_base_class import DeviceTab, define_state
from qtutils.qt.QtCore import*
from qtutils.qt.QtGui import *
from qtutils.qt.QtWidgets import *
from PyQt5.QtWidgets import QComboBox, QGridLayout, QLineEdit, QSpinBox
import time

class CUAServoMirrorTab(DeviceTab):
    def initialise_GUI ( self ):
        """Initializes the GUI tab for the mirror servos
        """
        
        # pull the layout of the tab so that we can place widgets in it
        layout = self.get_tab_layout()
        
        # Make it scrollable
        scroll = QScrollArea()
        layout.addWidget(scroll)

        # Get properties from connection table.
        device = self.settings['connection_table'].find_by_name(
            self.device_name
        )
        
        self.name = device.properties['name']
        self.com_port = device.properties['com_port']
        self.baud_rate = device.properties['baud_rate']
        self.mirror_mapping_dict = device.properties['mirror_mapping_dict']


        # various widgets we will put in the layout
        self.name_label_widgets = {}
        self.torque_checkbox_widgets = {}

        # getters and setters for the positions
        self.set_horizontal_label_widgets = {}
        self.set_horizontal_textbox_widgets = {}
        self.get_horizontal_label_widgets = {}
        self.get_horizontal_textbox_widgets = {}

        self.set_vertical_label_widgets = {}
        self.set_vertical_textbox_widgets = {}
        self.get_vertical_label_widgets = {}
        self.get_vertical_textbox_widgets = {}

        # buttons to set and read the position
        self.set_button_widgets = {}
        self.get_button_widgets = {}

        for row, mirror_name in enumerate(self.mirror_mapping_dict):
            # for each channel, make a new row to put the label, editable textbox, and button to send the contents of the text box
            cur_row = QGridLayout()
            
            # Name of the mirror
            self.name_label_widgets[mirror_name] = QLabel()
            self.name_label_widgets[mirror_name].setText(mirror_name)
            self.name_label_widgets[mirror_name].setAlignment(Qt.AlignLeft)
            #self.freq_label_widgets[channel_name].setFixedSize(150, 25)
            cur_row.addWidget(self.name_label_widgets[mirror_name], 0, 0)

            # Enable/disable torque
            self.torque_checkbox_widgets[mirror_name] = QCheckBox("Torque")
            self.torque_checkbox_widgets[mirror_name].setChecked(False)
            cur_row.addWidget(self.torque_checkbox_widgets[mirror_name], 1, 0)

            # labels and boxes for getting/setting horizontal position
            self.set_horizontal_label_widgets[mirror_name] = QLabel()
            self.set_horizontal_label_widgets[mirror_name].setText("Set H")
            self.set_horizontal_label_widgets[mirror_name].setAlignment(Qt.AlignLeft)
            cur_row.addWidget(self.set_horizontal_label_widgets[mirror_name], 0, 1)
            self.set_horizontal_textbox_widgets[mirror_name] = QLineEdit("0")
            self.set_horizontal_textbox_widgets[mirror_name].setAlignment(Qt.AlignCenter)
            cur_row.addWidget(self.set_horizontal_textbox_widgets[mirror_name], 0, 2)

            self.get_horizontal_label_widgets[mirror_name] = QLabel()
            self.get_horizontal_label_widgets[mirror_name].setText("Cur H")
            self.get_horizontal_label_widgets[mirror_name].setAlignment(Qt.AlignLeft)
            cur_row.addWidget(self.get_horizontal_label_widgets[mirror_name], 1, 1)
            self.get_horizontal_textbox_widgets[mirror_name] = QLabel()
            self.get_horizontal_textbox_widgets[mirror_name].setText("-----")
            self.get_horizontal_textbox_widgets[mirror_name].setAlignment(Qt.AlignCenter)
            cur_row.addWidget(self.get_horizontal_textbox_widgets[mirror_name], 1, 2)

            
            # labels and boxes for getting/setting vertical position
            self.set_vertical_label_widgets[mirror_name] = QLabel()
            self.set_vertical_label_widgets[mirror_name].setText("Set V")
            self.set_vertical_label_widgets[mirror_name].setAlignment(Qt.AlignLeft)
            cur_row.addWidget(self.set_vertical_label_widgets[mirror_name], 0, 3)
            self.set_vertical_textbox_widgets[mirror_name] = QLineEdit("0")
            self.set_vertical_textbox_widgets[mirror_name].setAlignment(Qt.AlignCenter)
            cur_row.addWidget(self.set_vertical_textbox_widgets[mirror_name], 0, 4)

            self.get_vertical_label_widgets[mirror_name] = QLabel()
            self.get_vertical_label_widgets[mirror_name].setText("Cur V")
            self.get_vertical_label_widgets[mirror_name].setAlignment(Qt.AlignLeft)
            cur_row.addWidget(self.get_vertical_label_widgets[mirror_name], 1, 3)
            self.get_vertical_textbox_widgets[mirror_name] = QLabel()
            self.get_vertical_textbox_widgets[mirror_name].setText("-----")
            self.get_vertical_textbox_widgets[mirror_name].setAlignment(Qt.AlignCenter)
            cur_row.addWidget(self.get_vertical_textbox_widgets[mirror_name], 1, 4)

            # Buttons for setting/getting position
            self.set_button_widgets[mirror_name] = QPushButton()
            self.set_button_widgets[mirror_name].setText("Set")
            self.set_button_widgets[mirror_name].setStyleSheet("border :1px solid black")
            cur_row.addWidget(self.set_button_widgets[mirror_name], 0, 5)

            self.get_button_widgets[mirror_name] = QPushButton()
            self.get_button_widgets[mirror_name].setText("Get")
            self.get_button_widgets[mirror_name].setStyleSheet("border :1px solid black")
            cur_row.addWidget(self.get_button_widgets[mirror_name], 1, 5)

            # add the row for the mirror
            layout.addLayout(cur_row)

        # connect the buttons to methods, pass in the name to the method
        for mirror_name in self.set_button_widgets:
            button = self.set_button_widgets[mirror_name]
            # this syntax passes in the name of the mirror to the function when the button is pressed
            # "state" is the button, we don't care about it so it isn't passed into the function
            button.clicked.connect(lambda state, x=mirror_name: self.set_position_on_click(x))

        for mirror_name in self.get_button_widgets:
            button = self.get_button_widgets[mirror_name]
            button.clicked.connect(lambda state, x=mirror_name: self.get_position_on_click(x))

        for mirror_name in self.torque_checkbox_widgets:
            button = self.torque_checkbox_widgets[mirror_name]
            button.clicked.connect(lambda state, x=mirror_name: self.torque_toggle(x))
        
        # initialize the values when we start up
        for name in self.mirror_mapping_dict:
            self.get_position_on_click(name)

        self.supports_smart_programming(True)

    MODE_MANUAL = 1
    @define_state(MODE_MANUAL,True)  
    def set_position_on_click(self, mirror_name):
        """Set the position for the mirror when the "set" button is pressed

        Args:
            mirror_name (str): name of the mirror that's going to be changed
        """

        # better to not use try/except and to check before casting
        try:
            # get the user-defined positions for the mirror (I think this is error checked in the worker class sdk functions
            # for the motors, but I should double check this later)
            # Also note that the positions are integers
            horizontal_position = int(self.set_horizontal_textbox_widgets[mirror_name].text())
            vertical_position = int(self.set_vertical_textbox_widgets[mirror_name].text())
            
            # yeet the mirror
            yield(self.queue_work('main_worker','set_position', mirror_name, horizontal_position, vertical_position))

        except:
            self.logger.debug("PLEASE ENTER A VALID INT")

        return

    @define_state(MODE_MANUAL, True)
    def get_position_on_click(self, mirror_name):
        """Get the position for the mirror when the "get" button is pressed

        Args:
            mirror_name (str): name of the mirror that's going to be changed
        """

        # get the positions
        horizontal_position, vertical_position = yield(self.queue_work('main_worker','get_position', mirror_name))
        # reflect the positions in the GUI
        self.get_horizontal_textbox_widgets[mirror_name].setText(str(horizontal_position))
        self.get_vertical_textbox_widgets[mirror_name].setText(str(vertical_position))
        self.set_horizontal_textbox_widgets[mirror_name].setText(str(horizontal_position))
        self.set_vertical_textbox_widgets[mirror_name].setText(str(vertical_position))

        return

    @define_state(MODE_MANUAL, True)
    def torque_toggle(self, mirror_name):
        """Enable/disable the mirrors motors. This allows us to turn the knobs by hand

        Args:
            mirror_name (str): name of the mirror that's going to be changed
        """

        result = yield(self.queue_work('main_worker','toggle_torque', mirror_name, self.torque_checkbox_widgets[mirror_name].isChecked()))

        return



    def initialise_workers(self):

        # Create and set the primary worker
        self.create_worker(
            'main_worker',
            'user_devices.CUAServoMirror.blacs_workers.CUAServoMirrorWorker',
            {   
                'name': self.name,
                'com_port': self.com_port,
                'baud_rate': self.baud_rate,
                'mirror_mapping_dict': self.mirror_mapping_dict,
            },
        )
        self.primary_worker = 'main_worker'

