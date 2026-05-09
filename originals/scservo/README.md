# Explanation

This class implements the ability to control many mirrors using a single controller. The code is based off of that found in the \scservo_sdk\ folder, obtained from here: Gitee.com/ftservo. In the \standalone_mirror_code\SCServo_Python\ folder, there is standalone code that can be used to interact with the mirrors, e.g. read_write.py. The mirror ID's can be found by using the \standalone_mirror_code\fddebug-master\fddebug-master\FD.exe program with the following instructions: 

1. Find the corresponding COM channel, then click Open 
2. (The Baud rate needs to be 1000000) 
3. Then click "Search", ID list should have something appear 
4. (ID of the motors seems by default will be 1 and 2. To avoid conflict, rename it to some other numbers. Rename can be done by clicking "programming"-ID) 

To instantiate the labscript devices class, use your version of the following syntax
CUAServoMirror(name="cheese_mirrors",
                mirror_mapping_dict={"cheese_mirror_1":(2, 4)}, # in the format of "name_of_mirror":(horizontal_id, vertical_id)
                com_port="COM3")

The motors on a single mirror together and have named them either the horizontal or vertical mirror.


 