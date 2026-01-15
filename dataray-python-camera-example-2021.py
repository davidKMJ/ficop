import wx
import wx.lib.activex
import csv
import comtypes.client



#Class that handles the event handling
class EventSink(object):
    def __init__(self,frame):
        self.counter=0
        self.frame = frame
    def DataReady(self):
        self.counter +=1
        self.frame.Title= "DataReady fired {0} times".format(self.counter)
class MyApp( wx.App ): 
    def OnClick(self,e):
        rb_selection = self.rb.GetStringSelection()
        if rb_selection == "WinCam":
            data = self.gd.ctrl.GetWinCamDataAsVariant()
            data = [[x] for x in data]
        else:
            p_selection = self.cb.GetStringSelection()
            if p_selection == "Profile_X":
                data = self.px.ctrl.GetProfileDataAsVariant()
                data = [[x] for x in data]
            elif p_selection == "PRofile_Y":
                data = self.py.ctrl.GetProfileDataAsVariant()
                data = [[x] for x in data]
            else:
                datax = self.px.ctrl.GetProfileDataAsVariant()
                datay = self.py.ctrl.GetPRofileDataAsVariant()
                data = [list(row) for row in zip(datax,datay)]
                #Makes a listof lists; X1 with Y1 in a list, etc...
            filename = self.ti.Value
            with open(filename,'w')as fp:
                w = csv.writer(fp, delimiter=',')
                w.writerows(data)

    def __init__( self, redirect=False, filename=None ):
        wx.App.__init__( self, redirect, filename )
        self.frame = wx.Frame( parent=None, id=wx.ID_ANY,size=(900,900), 
                              title='Python Interface to DataRay')
        #Panel
        p = wx.Panel(self.frame,wx.ID_ANY)
        #Get Data
        self.gd = wx.lib.activex.ActiveXCtrl(p, 'DATARAYOCX.GetDataCtrl.1')
        self.frame.Show()
        
        #EventSink
        sink = EventSink(self.frame)
        self.sink = comtypes.client.GetEvents(self.gd.ctrl,sink)
        #Button
        b1 = wx.lib.activex.ActiveXCtrl(parent=p,size=(200,50), pos=(7, 0),
                                        axID='DATARAYOCX.ButtonCtrl.1')
        b1.ctrl.ButtonID =297 #Id's for some ActiveX controls must be set
        
        b2 = wx.lib.activex.ActiveXCtrl(parent=p,size=(100,25), pos=(5, 55),
                                        axID='DATARAYOCX.ButtonCtrl.1')
        b2.ctrl.ButtonID =171
        b3 = wx.lib.activex.ActiveXCtrl(parent=p,size=(100,25), pos=(110,55),
                                        axID='DATARAYOCX.ButtonCtrl.1')
        b3.ctrl.ButtonID =172
        b4 = wx.lib.activex.ActiveXCtrl(parent=p,size=(100,25), pos=(5, 85),
                                        axID='DATARAYOCX.ButtonCtrl.1')
        b4.ctrl.ButtonID =177
        b4 = wx.lib.activex.ActiveXCtrl(parent=p,size=(100,25), pos=(110, 85),
                                        axID='DATARAYOCX.ButtonCtrl.1')
        b4.ctrl.ButtonID =179
        
        #Pictures
        tpic = wx.lib.activex.ActiveXCtrl(parent=p,size=(250,250), 
                            axID='DATARAYOCX.ThreeDviewCtrl.1',pos=(500,250))
        #Profiles
        self.px = wx.lib.activex.ActiveXCtrl(parent=p,size=(300,200),
                            axID='DATARAYOCX.ProfilesCtrl.1',pos=(0,600))
        self.px.ctrl.ProfileID=22
        self.py = wx.lib.activex.ActiveXCtrl(parent=p,size=(300,200),
                            axID='DATARAYOCX.ProfilesCtrl.1',pos=(600,600))
        self.py.ctrl.ProfileID = 23
         
        #CCDImage
        wx.lib.activex.ActiveXCtrl(parent=p,axID='DATARAYOCX.CCDimageCtrl.1',
                                   size=(250,250),pos=(250,250))
        
        #Custom controls
        t = wx.StaticText(p, label="File:", pos=(5, 115))
        self.ti = wx.TextCtrl(p, value="C:/Users/Public/Documents/output.csv",
                              pos=(30, 115), size=(170, -1))
        self.rb = wx.RadioBox(p, label="Data:", pos=(5, 140), 
                              choices=["Profile", "WinCam"])
        self.cb = wx.ComboBox(p, pos=(5,200), 
                              choices=[ "Profile_X", "Profile_Y", "Both"])
        self.cb.SetSelection(0)
        myb = wx.Button(p, label="Write", pos=(5,225))
        myb.Bind(wx.EVT_BUTTON, self.OnClick)
        self.gd.ctrl.StartDriver()
        
if __name__ == "__main__":
    app = MyApp()
    app.MainLoop()