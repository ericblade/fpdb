#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-
#    Copyright 2008, Carl Gherardi
#    
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#    
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU General Public License for more details.
#    
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
########################################################################

import sys
import logging
from HandHistoryConverter import *

# Class for converting Everleaf HH format.

class Everleaf(HandHistoryConverter):
    
    # Static regexes
    re_SplitHands  = re.compile(r"\n\n+")
    re_GameInfo    = re.compile(r"^(Blinds )?\$?(?P<SB>[.0-9]+)/\$?(?P<BB>[.0-9]+) ((?P<LTYPE>NL|PL) )?(?P<GAME>(Hold\'em|Omaha|7 Card Stud))", re.MULTILINE)
    re_HandInfo    = re.compile(r".*#(?P<HID>[0-9]+)\n.*\n(Blinds )?\$?(?P<SB>[.0-9]+)/\$?(?P<BB>[.0-9]+) (?P<GAMETYPE>.*) - (?P<DATETIME>\d\d\d\d/\d\d/\d\d - \d\d:\d\d:\d\d)\nTable (?P<TABLE>[- a-zA-Z]+)")
    re_Button      = re.compile(r"^Seat (?P<BUTTON>\d+) is the button", re.MULTILINE)
    re_PlayerInfo  = re.compile(r"^Seat (?P<SEAT>[0-9]+): (?P<PNAME>.*) \(\s+(\$ (?P<CASH>[.0-9]+) USD|new player|All-in) \)", re.MULTILINE)
    re_Board       = re.compile(r"\[ (?P<CARDS>.+) \]")
    
    def __init__(self, in_path = '-', out_path = '-', follow = False):
        """\
in_path   (default '-' = sys.stdin)
out_path  (default '-' = sys.stdout)
follow :  whether to tail -f the input"""
        HandHistoryConverter.__init__(self, in_path, out_path, sitename="Everleaf", follow=follow)
        logging.info("Initialising Everleaf converter class")
        self.filetype = "text"
        self.codepage = "cp1252"
        self.start()

    def compilePlayerRegexs(self,  players):
        if not players <= self.compiledPlayers: # x <= y means 'x is subset of y'
            # we need to recompile the player regexs.
            self.compiledPlayers = players
            player_re = "(?P<PNAME>" + "|".join(map(re.escape, players)) + ")"
            logging.debug("player_re: "+ player_re)
            self.re_PostSB          = re.compile(r"^%s: posts small blind \[\$? (?P<SB>[.0-9]+)" % player_re, re.MULTILINE)
            self.re_PostBB          = re.compile(r"^%s: posts big blind \[\$? (?P<BB>[.0-9]+)" % player_re, re.MULTILINE)
            self.re_PostBoth        = re.compile(r"^%s: posts both blinds \[\$? (?P<SBBB>[.0-9]+)" % player_re, re.MULTILINE)
            self.re_HeroCards       = re.compile(r"^Dealt to %s \[ (?P<CARDS>.*) \]" % player_re, re.MULTILINE)
            self.re_Action          = re.compile(r"^%s(?P<ATYPE>: bets| checks| raises| calls| folds)(\s\[\$ (?P<BET>[.\d]+) (USD|EUR)\])?" % player_re, re.MULTILINE)
            self.re_ShowdownAction  = re.compile(r"^%s shows \[ (?P<CARDS>.*) \]" % player_re, re.MULTILINE)
            self.re_CollectPot      = re.compile(r"^%s wins \$ (?P<POT>[.\d]+) (USD|EUR)(.*?\[ (?P<CARDS>.*?) \])?" % player_re, re.MULTILINE)
            self.re_SitsOut         = re.compile(r"^%s sits out" % player_re, re.MULTILINE)

    def readSupportedGames(self):
        return [["ring", "hold", "nl"],
                ["ring", "hold", "pl"],
                ["ring", "hold", "fl"],
                ["ring", "omahahi", "pl"]
               ]

    def determineGameType(self, handText):
        # Cheating with this regex, only support nlhe at the moment
        # Blinds $0.50/$1 PL Omaha - 2008/12/07 - 21:59:48
        # Blinds $0.05/$0.10 NL Hold'em - 2009/02/21 - 11:21:57
        # $0.25/$0.50 7 Card Stud - 2008/12/05 - 21:43:59
        
        # Tourney:
        # Everleaf Gaming Game #75065769
        # ***** Hand history for game #75065769 *****
        # Blinds 10/20 NL Hold'em - 2009/02/25 - 17:30:32
        # Table 2

        structure = "" # nl, pl, cn, cp, fl
        game      = ""

        m = self.re_GameInfo.search(handText)
        if m == None:
            logging.debug("Gametype didn't match")
            return None
        if m.group('LTYPE') == "NL":
            structure = "nl"
        elif m.group('LTYPE') == "PL":
            structure = "pl"
        else:
            structure = "fl" # we don't support it, but there should be how to detect it at least.

        if m.group('GAME') == "Hold\'em":
            game = "hold"
        elif m.group('GAME') == "Omaha":
            game = "omahahi"
        elif m.group('GAME') == "7 Card Stud":
            game = "studhi" # Everleaf currently only does Hi stud

        gametype = ["ring", game, structure, m.group('SB'), m.group('BB')]

        return gametype

    def readHandInfo(self, hand):
        m = self.re_HandInfo.search(hand.handText)
        if(m == None):
            logging.info("Didn't match re_HandInfo")
            logging.info(hand.handtext)
            return None
        logging.debug("HID %s, Table %s" % (m.group('HID'),  m.group('TABLE')))
        hand.handid =  m.group('HID')
        hand.tablename = m.group('TABLE')
        hand.maxseats = 6     # assume 6-max unless we have proof it's a larger/smaller game, since everleaf doesn't give seat max info

        # Believe Everleaf time is GMT/UTC, no transation necessary
        # Stars format (Nov 10 2008): 2008/11/07 12:38:49 CET [2008/11/07 7:38:49 ET]
        # or                        : 2008/11/07 12:38:49 ET
        # Not getting it in my HH files yet, so using
        # 2008/11/10 3:58:52 ET
        #TODO: Do conversion from GMT to ET
        #TODO: Need some date functions to convert to different timezones (Date::Manip for perl rocked for this)
        hand.starttime = time.strptime(m.group('DATETIME'), "%Y/%m/%d - %H:%M:%S")
        return

    def readPlayerStacks(self, hand):
        m = self.re_PlayerInfo.finditer(hand.handText)
        for a in m:
            seatnum = int(a.group('SEAT'))
            hand.addPlayer(seatnum, a.group('PNAME'), a.group('CASH'))
            if seatnum > 6:
                hand.maxseats = 10 # everleaf currently does 2/6/10 games, so if seats > 6 are in use, it must be 10-max.
                # TODO: implement lookup list by table-name to determine maxes, then fall back to 6 default/10 here, if there's no entry in the list?
            
        
    def markStreets(self, hand):
        # PREFLOP = ** Dealing down cards **
        # This re fails if,  say, river is missing; then we don't get the ** that starts the river.
        #m = re.search('(\*\* Dealing down cards \*\*\n)(?P<PREFLOP>.*?\n\*\*)?( Dealing Flop \*\* \[ (?P<FLOP1>\S\S), (?P<FLOP2>\S\S), (?P<FLOP3>\S\S) \])?(?P<FLOP>.*?\*\*)?( Dealing Turn \*\* \[ (?P<TURN1>\S\S) \])?(?P<TURN>.*?\*\*)?( Dealing River \*\* \[ (?P<RIVER1>\S\S) \])?(?P<RIVER>.*)', hand.handText,re.DOTALL)

        m =  re.search(r"\*\* Dealing down cards \*\*(?P<PREFLOP>.+(?=\*\* Dealing Flop \*\*)|.+)"
                       r"(\*\* Dealing Flop \*\*(?P<FLOP> \[ \S\S, \S\S, \S\S \].+(?=\*\* Dealing Turn \*\*)|.+))?"
                       r"(\*\* Dealing Turn \*\*(?P<TURN> \[ \S\S \].+(?=\*\* Dealing River \*\*)|.+))?"
                       r"(\*\* Dealing River \*\*(?P<RIVER> \[ \S\S \].+))?", hand.handText,re.DOTALL)

        hand.addStreets(m)

    def readCommunityCards(self, hand, street): # street has been matched by markStreets, so exists in this hand
        # If this has been called, street is a street which gets dealt community cards by type hand
        # but it might be worth checking somehow.
#        if street in ('FLOP','TURN','RIVER'):   # a list of streets which get dealt community cards (i.e. all but PREFLOP)
        logging.debug("readCommunityCards (%s)" % street)
        m = self.re_Board.search(hand.streets[street])
        cards = m.group('CARDS')
        cards = [card.strip() for card in cards.split(',')]
        hand.setCommunityCards(street=street, cards=cards)

    def readBlinds(self, hand):
        m = self.re_PostSB.search(hand.handText)
        if m is not None:
            hand.addBlind(m.group('PNAME'), 'small blind', m.group('SB'))
        else:
            logging.debug("No small blind")
            hand.addBlind(None, None, None)
        for a in self.re_PostBB.finditer(hand.handText):
            hand.addBlind(a.group('PNAME'), 'big blind', a.group('BB'))
        for a in self.re_PostBoth.finditer(hand.handText):
            hand.addBlind(a.group('PNAME'), 'both', a.group('SBBB'))

    def readButton(self, hand):
        hand.buttonpos = int(self.re_Button.search(hand.handText).group('BUTTON'))

    def readHeroCards(self, hand):
        m = self.re_HeroCards.search(hand.handText)
        if m:
            hand.hero = m.group('PNAME')
            # "2c, qh" -> ["2c","qc"]
            # Also works with Omaha hands.
            cards = m.group('CARDS')
            cards = [card.strip() for card in cards.split(',')]
            hand.addHoleCards(cards, m.group('PNAME'))
        else:
            #Not involved in hand
            hand.involved = False

    def readAction(self, hand, street):
        logging.debug("readAction (%s)" % street)
        m = self.re_Action.finditer(hand.streets[street])
        for action in m:
            if action.group('ATYPE') == ' raises':
                hand.addCallandRaise( street, action.group('PNAME'), action.group('BET') )
            elif action.group('ATYPE') == ' calls':
                hand.addCall( street, action.group('PNAME'), action.group('BET') )
            elif action.group('ATYPE') == ': bets':
                hand.addBet( street, action.group('PNAME'), action.group('BET') )
            elif action.group('ATYPE') == ' folds':
                hand.addFold( street, action.group('PNAME'))
            elif action.group('ATYPE') == ' checks':
                hand.addCheck( street, action.group('PNAME'))
            else:
                logging.debug("Unimplemented readAction: %s %s" %(action.group('PNAME'),action.group('ATYPE'),))


    def readShowdownActions(self, hand):
        """Reads lines where holecards are reported in a showdown"""
        logging.debug("readShowdownActions")
        for shows in self.re_ShowdownAction.finditer(hand.handText):
            cards = shows.group('CARDS')
            cards = cards.split(', ')
            logging.debug("readShowdownActions %s %s" %(cards, shows.group('PNAME')))
            hand.addShownCards(cards, shows.group('PNAME'))


    def readCollectPot(self,hand):
        for m in self.re_CollectPot.finditer(hand.handText):
            hand.addCollectPot(player=m.group('PNAME'),pot=m.group('POT'))

    def readShownCards(self,hand):
        """Reads lines where hole & board cards are mixed to form a hand (summary lines)"""
        for m in self.re_CollectPot.finditer(hand.handText):
            if m.group('CARDS') is not None:
                cards = m.group('CARDS')
                cards = cards.split(', ')
                player = m.group('PNAME')
                logging.debug("readShownCards %s cards=%s" % (player, cards))
                hand.addShownCards(cards=None, player=m.group('PNAME'), holeandboard=cards)



if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-i", "--input", dest="ipath", help="parse input hand history", default="regression-test-files/everleaf/Speed_Kuala_full.txt")
    parser.add_option("-o", "--output", dest="opath", help="output translation to", default="-")
    parser.add_option("-f", "--follow", dest="follow", help="follow (tail -f) the input", action="store_true", default=False)
    parser.add_option("-q", "--quiet",
                  action="store_const", const=logging.CRITICAL, dest="verbosity", default=logging.INFO)
    parser.add_option("-v", "--verbose",
                  action="store_const", const=logging.INFO, dest="verbosity")
    parser.add_option("--vv",
                  action="store_const", const=logging.DEBUG, dest="verbosity")

    (options, args) = parser.parse_args()

    LOG_FILENAME = './logging.out'
    logging.basicConfig(filename=LOG_FILENAME,level=options.verbosity)

    e = Everleaf(in_path = options.ipath, out_path = options.opath, follow = options.follow)

