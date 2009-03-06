# -*- coding: utf-8 -*-
import EverleafToFpdb
import py
class TestEverleaf:
    def testGameInfo1(self):
        e = EverleafToFpdb.Everleaf(autostart=False)
        g = """Everleaf Gaming Game #3732225
***** Hand history for game #3732225 *****
Blinds  €0.50/ €1 NL Hold'em - 2009/01/11 - 16:09:40
Table Casino Lyon Vert 58
Seat 3 is the button
Total number of players: 6"""
        assert e.determineGameType(g) == {'sb':'0.50', 'bb':'1','game':"hold", 'currency':'EUR', 'limit':'nl'}

        
    def testGameInfo2(self):
        e = EverleafToFpdb.Everleaf(autostart=False)
        g = """Everleaf Gaming Game #55198191
***** Hand history for game #55198191 *****
Blinds $0.50/$1 NL Hold'em - 2008/09/01 - 10:02:11
Table Speed Kuala
Seat 8 is the button
Total number of players: 10"""
        assert e.determineGameType(g) == {'sb':'0.50', 'bb':'1','game':"hold", 'currency':'USD', 'limit':'nl'}

    def testGameInfo3(self):
        # Note: It looks difficult to distinguish T$ from play money.
        e = EverleafToFpdb.Everleaf(autostart=False)
        g = """Everleaf Gaming Game #75065769
***** Hand history for game #75065769 *****
Blinds 10/20 NL Hold'em - 2009/02/25 - 17:30:32
Table 2
Seat 1 is the button
Total number of players: 10"""
        assert e.determineGameType(g) == {'sb':'10', 'bb':'20','game':"hold", 'currency':'T$', 'limit':'nl'}
        