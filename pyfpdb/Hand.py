#!/usr/bin/python

#Copyright 2008 Carl Gherardi
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, version 3 of the License.
#   
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#GNU General Public License for more details.
#       
#You should have received a copy of the GNU Affero General Public License
#along with this program. If not, see <http://www.gnu.org/licenses/>.
#In the "official" distribution you can find the license in
#agpl-3.0.txt in the docs folder of the package.

import re
import sys
import traceback
import logging
import os
import os.path
from decimal import Decimal
import operator
import time
from copy import deepcopy
from Exceptions import *

class Hand:
    UPS = {'a':'A', 't':'T', 'j':'J', 'q':'Q', 'k':'K', 'S':'s', 'C':'c', 'H':'h', 'D':'d'}
    def __init__(self, sitename, gametype, handText):
        self.sitename = sitename
        self.gametype = gametype
        self.handText = handText
        self.handid = 0
        self.tablename = "Slartibartfast"
        self.hero = "Hiro"
        self.maxseats = 10
        self.counted_seats = 0
        self.buttonpos = 0
        self.seating = []
        self.players = []
        self.posted = []
        self.involved = True

        # Collections indexed by street names
        self.bets = {}
        self.lastBet = {}
        self.streets = {}
        self.actions = {} # [['mct','bets','$10'],['mika','folds'],['carlg','raises','$20']]
        self.board = {} # dict from street names to community cards
        for street in self.streetList:
            self.streets[street] = "" # portions of the handText, filled by markStreets()
            self.bets[street] = {}
            self.lastBet[street] = 0
            self.actions[street] = []
            self.board[street] = []
        
        
        # Collections indexed by player names
        self.holecards = {} # dict from player names to dicts by street ... of tuples ... of holecards
        self.stacks = {}
        self.collected = [] #list of ?
        self.collectees = {} # dict from player names to amounts collected (?)

        # Sets of players
        self.shown = set()
        self.folded = set()

#        self.action = []
        # Things to do with money
        self.pot = Pot()
        self.totalpot = None
        self.totalcollected = None
        self.rake = None


    def addPlayer(self, seat, name, chips):
        """\
Adds a player to the hand, and initialises data structures indexed by player.
seat    (int) indicating the seat
name    (string) player name
chips   (string) the chips the player has at the start of the hand (can be None)
If a player has None chips he won't be added."""
        if chips is not None:
            self.players.append([seat, name, chips])
            self.stacks[name] = Decimal(chips)
            self.holecards[name] = []
            self.pot.addPlayer(name)
            for street in self.streetList:
                self.bets[street][name] = []
                self.holecards[name] = {} # dict from street names.


    def addStreets(self, match):
        # go through m and initialise actions to empty list for each street.
        if match:
            self.streets.update(match.groupdict())
            logging.debug("markStreets:\n"+ str(self.streets))
        else:
            logging.error("markstreets didn't match")

#def addHoleCards -- to Holdem subclass



    def checkPlayerExists(self,player):
        if player not in [p[1] for p in self.players]:
            print "checkPlayerExists", player, "fail"
            raise FpdbParseError

    def discardHoleCards(self, cards, player):
        try:
            self.checkPlayerExists(player)
            for card in cards:
                self.holecards[player].remove(card)
        except FpdbParseError, e:
            pass
        except ValueError:
            print "[ERROR] discardHoleCard tried to discard a card %s didn't have" % (player,)

    def setCommunityCards(self, street, cards):
        logging.debug("setCommunityCards %s %s" %(street,  cards))
        self.board[street] = [self.card(c) for c in cards]

    def card(self,c):
        """upper case the ranks but not suits, 'atjqk' => 'ATJQK'"""
        for k,v in self.UPS.items():
            c = c.replace(k,v)
        return c

    def addAnte(self, player, ante):
        if player is not None:
            self.bets['ANTES'][player].append(Decimal(ante))
            self.stacks[player] -= Decimal(ante)
            act = (player, 'posts', "ante", ante, self.stacks[player]==0)
            self.actions['ANTES'].append(act)
            self.pot.addMoney(player, Decimal(ante))

    def addBlind(self, player, blindtype, amount):
        # if player is None, it's a missing small blind.
        # The situation we need to cover are:
        # Player in small blind posts
        #   - this is a bet of 1 sb, as yet uncalled.
        # Player in the big blind posts
        #   - this is a call of 1 sb and a raise to 1 bb
        # 
        
        logging.debug("addBlind: %s posts %s, %s" % (player, blindtype, amount))
        if player is not None:
            self.bets['PREFLOP'][player].append(Decimal(amount))
            self.stacks[player] -= Decimal(amount)
            #print "DEBUG %s posts, stack %s" % (player, self.stacks[player])
            act = (player, 'posts', blindtype, amount, self.stacks[player]==0)
            self.actions['BLINDSANTES'].append(act)
            self.pot.addMoney(player, Decimal(amount))
            if blindtype == 'big blind':
                self.lastBet['PREFLOP'] = Decimal(amount)            
            elif blindtype == 'both':
                # extra small blind is 'dead'
                self.lastBet['PREFLOP'] = Decimal(self.bb)
        self.posted = self.posted + [[player,blindtype]]
        #print "DEBUG: self.posted: %s" %(self.posted)



    def addCall(self, street, player=None, amount=None):
        # Potentially calculate the amount of the call if not supplied
        # corner cases include if player would be all in
        if amount is not None:
            self.bets[street][player].append(Decimal(amount))
            #self.lastBet[street] = Decimal(amount)
            self.stacks[player] -= Decimal(amount)
            #print "DEBUG %s calls %s, stack %s" % (player, amount, self.stacks[player])
            act = (player, 'calls', amount, self.stacks[player]==0)
            self.actions[street].append(act)
            self.pot.addMoney(player, Decimal(amount))
            
    def addRaiseBy(self, street, player, amountBy):
        """\
Add a raise by amountBy on [street] by [player] 
"""
        #Given only the amount raised by, the amount of the raise can be calculated by
        # working out how much this player has already in the pot 
        #   (which is the sum of self.bets[street][player])
        # and how much he needs to call to match the previous player 
        #   (which is tracked by self.lastBet)
        # let Bp = previous bet 
        #     Bc = amount player has committed so far
        #     Rb = raise by
        # then: C = Bp - Bc (amount to call)
        #      Rt = Bp + Rb (raise to)
        # 
        self.checkPlayerExists(player)
        Rb = Decimal(amountBy)
        Bp = self.lastBet[street]
        Bc = reduce(operator.add, self.bets[street][player], 0)
        C = Bp - Bc
        Rt = Bp + Rb
        
        self.bets[street][player].append(C + Rb)
        self.stacks[player] -= (C + Rb)
        self.actions[street] += [(player, 'raises', Rb, Rt, C, self.stacks[player]==0)]
        self.lastBet[street] = Rt

    def addCallandRaise(self, street, player, amount):
        """\
For sites which by "raises x" mean "calls and raises putting a total of x in the por". """
        self.checkPlayerExists(player)
        CRb = Decimal(amount)
        Bp = self.lastBet[street]
        Bc = reduce(operator.add, self.bets[street][player], 0)
        C = Bp - Bc
        Rb = CRb - C
        Rt = Bp + Rb
        
        self._addRaise(street, player, C, Rb, Rt)

    def addRaiseTo(self, street, player, amountTo):
        """\
Add a raise on [street] by [player] to [amountTo]
"""
        #CG - No idea if this function has been test/verified
        self.checkPlayerExists(player)
        Bp = self.lastBet[street]
        Bc = reduce(operator.add, self.bets[street][player], 0)
        Rt = Decimal(amountTo)
        C = Bp - Bc
        Rb = Rt - C
        self._addRaise(street, player, C, Rb, Rt)

    def _addRaise(self, street, player, C, Rb, Rt):
        self.bets[street][player].append(C + Rb)
        self.stacks[player] -= (C + Rb)
        act = (player, 'raises', Rb, Rt, C, self.stacks[player]==0)
        self.actions[street].append(act)
        self.lastBet[street] = Rt # TODO check this is correct
        self.pot.addMoney(player, C+Rb)
    
        
        
    def addBet(self, street, player, amount):
        self.checkPlayerExists(player)
        self.bets[street][player].append(Decimal(amount))
        self.stacks[player] -= Decimal(amount)
        #print "DEBUG %s bets %s, stack %s" % (player, amount, self.stacks[player])
        act = (player, 'bets', amount, self.stacks[player]==0)
        self.actions[street].append(act)
        self.lastBet[street] = Decimal(amount)
        self.pot.addMoney(player, Decimal(amount))
        

    def addFold(self, street, player):
        #print "DEBUG: %s %s folded" % (street, player)
        self.checkPlayerExists(player)
        self.folded.add(player)
        self.pot.addFold(player)
        self.actions[street].append((player, 'folds'))
        

    def addCheck(self, street, player):
        #print "DEBUG: %s %s checked" % (street, player)
        self.checkPlayerExists(player)
        self.actions[street].append((player, 'checks'))


    def addCollectPot(self,player, pot):
        #print "DEBUG: %s collected %s" % (player, pot)
        self.checkPlayerExists(player)
        self.collected = self.collected + [[player, pot]]
        if player not in self.collectees:
            self.collectees[player] = Decimal(pot)
        else:
            self.collectees[player] += Decimal(pot)


    def totalPot(self):
        """If all bets and blinds have been added, totals up the total pot size"""
        
        # This gives us the total amount put in the pot
        if self.totalpot is None:
            self.pot.end()
            self.totalpot = self.pot.total

        # This gives us the amount collected, i.e. after rake
        if self.totalcollected is None:
            self.totalcollected = 0;
            #self.collected looks like [[p1,amount][px,amount]]
            for entry in self.collected:
                self.totalcollected += Decimal(entry[1])




    def getGameTypeAsString(self):
        """\
Map the tuple self.gametype onto the pokerstars string describing it
"""
        # currently it appears to be something like ["ring", "hold", "nl", sb, bb]:
        gs = {"hold"       : "Hold'em",
              "omahahi"    : "Omaha",
              "omahahilo"  : "FIXME",
              "razz"       : "Razz",
              "studhi"     : "FIXME",
              "studhilo"   : "FIXME",
              "fivedraw"   : "5 Card Draw",
              "27_1draw"   : "FIXME",
              "27_3draw"   : "Triple Draw 2-7 Lowball",
              "badugi"     : "FIXME"
             }
        ls = {"nl"  : "No Limit",
              "pl"  : "Pot Limit",
              "fl"  : "Limit",
              "cn"  : "Cap No Limit",
              "cp"  : "Cap Pot Limit"
             }

        logging.debug("gametype: %s" %(self.gametype))
        retstring = "%s %s" %(gs[self.gametype[1]], ls[self.gametype[2]])
        
        return retstring

    def lookupLimitBetSize(self):
        #Lookup table  for limit games
        betlist = {
            "Everleaf" : {  "0.10" : ("0.02", "0.05"),
                            "0.20" : ("0.05", "0.10"),
                            "0.50" : ("0.10", "0.25"),
                            "1.00" : ("0.25", "0.50")
                },
            "FullTilt" : {  "0.10" : ("0.02", "0.05"),
                            "0.20" : ("0.05", "0.10"),
                            "1"    : ("0.25", "0.50"),
                            "2"    : ("0.50", "1"),
                            "4"    : ("1", "2")
                }
            }
        return betlist[self.sitename][self.bb]


    def writeHand(self, fh=sys.__stdout__):
        print >>fh, "Override me"

    def printHand(self):
        self.writeHand(sys.stdout)

    def printActionLine(self, act, fh):
        if act[1] == 'folds':
            print >>fh, _("%s: folds " %(act[0]))
        elif act[1] == 'checks':
            print >>fh, _("%s: checks " %(act[0]))
        elif act[1] == 'calls':
            print >>fh, _("%s: calls $%s%s" %(act[0], act[2], ' and is all-in' if act[3] else ''))
        elif act[1] == 'bets':
            print >>fh, _("%s: bets $%s%s" %(act[0], act[2], ' and is all-in' if act[3] else ''))
        elif act[1] == 'raises':
            print >>fh, _("%s: raises $%s to $%s%s" %(act[0], act[2], act[3], ' and is all-in' if act[5] else ''))
        elif act[1] == 'posts':
            if(act[2] == "small blind"):
                print >>fh, _("%s: posts small blind $%s" %(act[0], act[3]))
            elif(act[2] == "big blind"):
                print >>fh, _("%s: posts big blind $%s" %(act[0], act[3]))
            elif(act[2] == "both"):
                print >>fh, _("%s: posts small & big blinds $%s" %(act[0], act[3]))

class HoldemOmahaHand(Hand):
    def __init__(self, hhc, sitename, gametype, handText):
        if gametype[1] not in ["hold","omaha"]:
            pass # or indeed don't pass and complain instead
        logging.debug("HoldemOmahaHand")
        self.streetList = ['BLINDSANTES', 'PREFLOP','FLOP','TURN','RIVER'] # a list of the observed street names in order
        self.communityStreets = ['FLOP', 'TURN', 'RIVER']
        self.actionStreets = ['PREFLOP','FLOP','TURN','RIVER']
        Hand.__init__(self, sitename, gametype, handText)
        self.sb = gametype[3]
        self.bb = gametype[4]
        
        #Populate a HoldemOmahaHand
        #Generally, we call 'read' methods here, which get the info according to the particular filter (hhc) 
        # which then invokes a 'addXXX' callback
        hhc.readHandInfo(self)
        hhc.readPlayerStacks(self)
        hhc.compilePlayerRegexs(players = set([player[1] for player in self.players]))
        hhc.markStreets(self)
        hhc.readBlinds(self)
        hhc.readButton(self)
        hhc.readHeroCards(self)
        hhc.readShowdownActions(self)
        # Read actions in street order
        for street in self.communityStreets:
            if self.streets[street]:
                hhc.readCommunityCards(self, street)
        for street in self.actionStreets:
            if self.streets[street]:
                hhc.readAction(self, street)
        hhc.readCollectPot(self)
        hhc.readShownCards(self)
        self.totalPot() # finalise it (total the pot)
        hhc.getRake(self)

    def addHoleCards(self, cards, player):
        """\
Assigns observed holecards to a player.
cards   list of card bigrams e.g. ['2h','Jc']
player  (string) name of player
"""
        logging.debug("addHoleCards %s %s" % (cards, player))
        try:
            self.checkPlayerExists(player)
            cardset = set(self.card(c) for c in cards)
            if 'PREFLOP' in self.holecards[player]:
                self.holecards[player]['PREFLOP'].update(cardset)
            else:
                self.holecards[player]['PREFLOP'] = cardset
        except FpdbParseError, e:
            print "[ERROR] Tried to add holecards for unknown player: %s" % (player,)

    def addShownCards(self, cards, player, holeandboard=None):
        """\
For when a player shows cards for any reason (for showdown or out of choice).
Card ranks will be uppercased
"""
        logging.debug("addShownCards %s hole=%s all=%s" % (player, cards,  holeandboard))
        if cards is not None:
            self.shown.add(player)
            self.addHoleCards(cards,player)
        elif holeandboard is not None:
            holeandboard = set([self.card(c) for c in holeandboard])
            board = set([c for s in self.board.values() for c in s])
            self.addHoleCards(holeandboard.difference(board),player)


    def writeHand(self, fh=sys.__stdout__):
        # PokerStars format.
        print >>fh, _("%s Game #%s: %s ($%s/$%s) - %s" %("PokerStars", self.handid, self.getGameTypeAsString(), self.sb, self.bb, time.strftime('%Y/%m/%d - %H:%M:%S (ET)', self.starttime)))
        print >>fh, _("Table '%s' %d-max Seat #%s is the button" %(self.tablename, self.maxseats, self.buttonpos))
        
        players_who_act_preflop = set([x[0] for x in self.actions['PREFLOP']])

        for player in [x for x in self.players if x[1] in players_who_act_preflop]:
            #Only print stacks of players who do something preflop
            print >>fh, _("Seat %s: %s ($%s)" %(player[0], player[1], player[2]))


        #May be more than 1 bb posting
        if self.gametype[2] == "fl":
            (smallbet, bigbet) = self.lookupLimitBetSize()
        else:
            smallbet = self.sb
            bigbet = self.bb

#        for a in self.posted:
#            if(a[1] == "small blind"):
#               print >>fh, _("%s: posts small blind $%s" %(a[0], smallbet))
#            if(a[1] == "big blind"):
#                print >>fh, _("%s: posts big blind $%s" %(a[0], bigbet))
#            if(a[1] == "both"):
#                print >>fh, _("%s: posts small & big blinds $%.2f" %(a[0], (Decimal(smallbet) + Decimal(bigbet))))
# I think these can just be actions in 'blindsantes' round

        if self.actions['BLINDSANTES']:
            for act in self.actions['BLINDSANTES']:
                self.printActionLine(act, fh)
        
        print >>fh, _("*** HOLE CARDS ***")
        if self.involved:
            print >>fh, _("Dealt to %s [%s]" %(self.hero , " ".join(self.holecards[self.hero]['PREFLOP'])))

        if self.actions['PREFLOP']:
            for act in self.actions['PREFLOP']:
                self.printActionLine(act, fh)

        if self.board['FLOP']:
            print >>fh, _("*** FLOP *** [%s]" %( " ".join(self.board['FLOP'])))
        if self.actions['FLOP']:
            for act in self.actions['FLOP']:
                self.printActionLine(act, fh)

        if self.board['TURN']:
            print >>fh, _("*** TURN *** [%s] [%s]" %( " ".join(self.board['FLOP']), " ".join(self.board['TURN'])))
        if self.actions['TURN']:
            for act in self.actions['TURN']:
                self.printActionLine(act, fh)

        if self.board['RIVER']:
            print >>fh, _("*** RIVER *** [%s] [%s]" %(" ".join(self.board['FLOP']+self.board['TURN']), " ".join(self.board['RIVER']) ))
        if self.actions['RIVER']:
            for act in self.actions['RIVER']:
                self.printActionLine(act, fh)


        #Some sites don't have a showdown section so we have to figure out if there should be one
        # The logic for a showdown is: at the end of river action there are at least two players in the hand
        # we probably don't need a showdown section in pseudo stars format for our filtering purposes
        if 'SHOWDOWN' in self.actions:
            print >>fh, _("*** SHOW DOWN ***")
            #TODO: Complete SHOWDOWN

        # Current PS format has the lines:
        # Uncalled bet ($111.25) returned to s0rrow
        # s0rrow collected $5.15 from side pot
        # stervels: shows [Ks Qs] (two pair, Kings and Queens)
        # stervels collected $45.35 from main pot
        # Immediately before the summary.
        # The current importer uses those lines for importing winning rather than the summary
        for name in self.pot.returned:
            print >>fh, _("Uncalled bet ($%s) returned to %s" %(self.pot.returned[name],name))
        for entry in self.collected:
            print >>fh, _("%s collected $%s from x pot" %(entry[0], entry[1]))

        print >>fh, _("*** SUMMARY ***")
        print >>fh, "%s | Rake $%.2f" % (self.pot, self.rake)

        board = []
        for s in self.board.values():
            board += s
        if board:   # sometimes hand ends preflop without a board
            print >>fh, _("Board [%s]" % (" ".join(board)))

        for player in [x for x in self.players if x[1] in players_who_act_preflop]:
            seatnum = player[0]
            name = player[1]
            if name in self.collectees and name in self.shown:
                print >>fh, _("Seat %d: %s showed [%s] and won ($%s)" % (seatnum, name, " ".join(self.holecards[name]['PREFLOP']), self.collectees[name]))
            elif name in self.collectees:
                print >>fh, _("Seat %d: %s collected ($%s)" % (seatnum, name, self.collectees[name]))
            elif name in self.shown:
                print >>fh, _("Seat %d: %s showed [%s]" % (seatnum, name, " ".join(self.holecards[name]['PREFLOP'])))
            elif name in self.folded:
                print >>fh, _("Seat %d: %s folded" % (seatnum, name))
            else:
                print >>fh, _("Seat %d: %s mucked" % (seatnum, name))

        print >>fh, "\n\n"



class StudHand(Hand):
    def __init__(self, hhc, sitename, gametype, handText):
        if gametype[1] not in ["razz","stud","stud8"]:
            pass # or indeed don't pass and complain instead
        self.streetList = ['ANTES','THIRD','FOURTH','FIFTH','SIXTH','SEVENTH'] # a list of the observed street names in order
        self.holeStreets = ['ANTES','THIRD','FOURTH','FIFTH','SIXTH','SEVENTH']
        Hand.__init__(self, sitename, gametype, handText)
        self.sb = gametype[3]
        self.bb = gametype[4]
        #Populate the StudHand
        #Generally, we call a 'read' method here, which gets the info according to the particular filter (hhc) 
        # which then invokes a 'addXXX' callback
        hhc.readHandInfo(self)
        hhc.readPlayerStacks(self)
        hhc.compilePlayerRegexs(players = set([player[1] for player in self.players]))
        hhc.markStreets(self)
        hhc.readAntes(self)
        hhc.readBringIn(self)
#        hhc.readShowdownActions(self) # not done yet
        # Read actions in street order
        for street in self.streetList:            
            if self.streets[street]:
                logging.debug(street)
                logging.debug(self.streets[street])
                hhc.readStudPlayerCards(self, street)
                hhc.readAction(self, street)
        hhc.readCollectPot(self)
#        hhc.readShownCards(self) # not done yet
        self.totalPot() # finalise it (total the pot)
        hhc.getRake(self)

    def addPlayerCards(self, player,  street,  open=[],  closed=[]):
        """\
Assigns observed cards to a player.
player  (string) name of player
street  (string) the street name (in streetList)
open  list of card bigrams e.g. ['2h','Jc'], dealt face up
closed    likewise, but known only to player
"""
        logging.debug("addPlayerCards %s, o%s x%s" % (player,  open, closed))
        try:
            self.checkPlayerExists(player)
            self.holecards[player][street] = (open, closed)
#            cards = set([self.card(c) for c in cards])
#            self.holecards[player].update(cards)
        except FpdbParseError, e:
            print "[ERROR] Tried to add holecards for unknown player: %s" % (player,)

    def addBringIn(self, player, bringin):
        if player is not None:
            logging.debug("Bringin: %s, %s" % (player , bringin))
            self.bets['THIRD'][player].append(Decimal(bringin))
            self.stacks[player] -= Decimal(bringin)
            act = (player, 'bringin', "bringin", bringin, self.stacks[player]==0)
            self.actions['THIRD'].append(act)
            self.pot.addMoney(player, Decimal(bringin))
    
    def writeHand(self, fh=sys.__stdout__):
        # PokerStars format.
        print >>fh, _("%s Game #%s: %s ($%s/$%s) - %s" %("PokerStars", self.handid, self.getGameTypeAsString(), self.sb, self.bb, time.strftime('%Y/%m/%d - %H:%M:%S (ET)', self.starttime)))
        print >>fh, _("Table '%s' %d-max Seat #%s is the button" %(self.tablename, self.maxseats, self.buttonpos))
        
        players_who_post_antes = set([x[0] for x in self.actions['ANTES']])

        for player in [x for x in self.players if x[1] in players_who_post_antes]:
            #Only print stacks of players who do something preflop
            print >>fh, _("Seat %s: %s ($%s)" %(player[0], player[1], player[2]))

        if 'ANTES' in self.actions:
            for act in self.actions['ANTES']:
                print >>fh, _("%s: posts the ante $%s" %(act[0], act[3]))

        if 'THIRD' in self.actions:
            print >>fh, _("*** 3RD STREET ***")
            for player in [x[1] for x in self.players if x[1] in players_who_post_antes]:
                print player,  self.holecards[player]
                (closed,  open) = self.holecards[player]['THIRD']
                print >>fh, _("Dealt to %s:%s%s") % (player, " [" + " ".join(closed) + "]" if closed else " ",  " [" + " ".join(open) + "]" if open else " ")
            for act in self.actions['THIRD']:
                #FIXME: Need some logic here for bringin vs completes
                self.printActionLine(act, fh)

        if 'FOURTH' in self.actions:
            print >>fh, _("*** 4TH STREET ***")
            for act in self.actions['FOURTH']:
                self.printActionLine(act, fh)

        if 'FIFTH' in self.actions:
            print >>fh, _("*** 5TH STREET ***")
            for act in self.actions['FIFTH']:
                self.printActionLine(act, fh)

        if 'SIXTH' in self.actions:
            print >>fh, _("*** 6TH STREET ***")
            for act in self.actions['SIXTH']:
                self.printActionLine(act, fh)

        if 'SEVENTH' in self.actions:
            print >>fh, _("*** 7TH STREET ***")
            for act in self.actions['SEVENTH']:
                self.printActionLine(act, fh)

        #Some sites don't have a showdown section so we have to figure out if there should be one
        # The logic for a showdown is: at the end of river action there are at least two players in the hand
        # we probably don't need a showdown section in pseudo stars format for our filtering purposes
        if 'SHOWDOWN' in self.actions:
            print >>fh, _("*** SHOW DOWN ***")
            # TODO: print showdown lines.

        # Current PS format has the lines:
        # Uncalled bet ($111.25) returned to s0rrow
        # s0rrow collected $5.15 from side pot
        # stervels: shows [Ks Qs] (two pair, Kings and Queens)
        # stervels collected $45.35 from main pot
        # Immediately before the summary.
        # The current importer uses those lines for importing winning rather than the summary
        for name in self.pot.returned:
            print >>fh, _("Uncalled bet ($%s) returned to %s" %(self.pot.returned[name],name))
        for entry in self.collected:
            print >>fh, _("%s collected $%s from x pot" %(entry[0], entry[1]))

        print >>fh, _("*** SUMMARY ***")
        print >>fh, "%s | Rake $%.2f" % (self.pot, self.rake)
        #print >>fh, _("Total pot $%s | Rake $%.2f" % (self.totalpot, self.rake)) # TODO: side pots

        board = []
        for s in self.board.values():
            board += s
        if board:   # sometimes hand ends preflop without a board
            print >>fh, _("Board [%s]" % (" ".join(board)))

        for player in [x for x in self.players if x[1] in players_who_post_antes]:
            seatnum = player[0]
            name = player[1]
            if name in self.collectees and name in self.shown:
                print >>fh, _("Seat %d: %s showed [%s] and won ($%s)" % (seatnum, name, " ".join(self.holecards[name]), self.collectees[name]))
            elif name in self.collectees:
                print >>fh, _("Seat %d: %s collected ($%s)" % (seatnum, name, self.collectees[name]))
            elif name in self.shown:
                print >>fh, _("Seat %d: %s showed [%s]" % (seatnum, name, " ".join(self.holecards[name])))
            elif name in self.folded:
                print >>fh, _("Seat %d: %s folded" % (seatnum, name))
            else:
                print >>fh, _("Seat %d: %s mucked" % (seatnum, name))

        print >>fh, "\n\n"



class Pot(object):


    def __init__(self):
        self.contenders = set()
        self.committed = {}
        self.total = None
        self.returned = {}
    
    def addPlayer(self,player):
        self.committed[player] = Decimal(0)
    
    def addFold(self, player):
        # addFold must be called when a player folds
        self.contenders.discard(player)
        
    def addMoney(self, player, amount):
        # addMoney must be called for any actions that put money in the pot, in the order they occur
        self.contenders.add(player)
        self.committed[player] += amount

    def end(self):
        self.total = sum(self.committed.values())
        
        # Return any uncalled bet.
        committed = sorted([ (v,k) for (k,v) in self.committed.items()])
        lastbet = committed[-1][0] - committed[-2][0]
        if lastbet > 0: # uncalled
            returnto = committed[-1][1]
            #print "DEBUG: returning %f to %s" % (lastbet, returnto)
            self.total -= lastbet
            self.committed[returnto] -= lastbet
            self.returned[returnto] = lastbet


        # Work out side pots
        commitsall = sorted([(v,k) for (k,v) in self.committed.items() if v >0])

        self.pots = []
        while len(commitsall) > 0:
            commitslive = [(v,k) for (v,k) in commitsall if k in self.contenders]
            v1 = commitslive[0][0]        
            self.pots += [sum([min(v,v1) for (v,k) in commitsall])]
            commitsall = [((v-v1),k) for (v,k) in commitsall if v-v1 >0]

        # TODO: I think rake gets taken out of the pots.
        # so it goes:
        # total pot x. main pot y, side pot z. | rake r
        # and y+z+r = x
        # for example:
        # Total pot $124.30 Main pot $98.90. Side pot $23.40. | Rake $2
        
    def __str__(self):
        if self.total is None:
            print "call Pot.end() before printing pot total"
            # NB if I'm sure end() is idempotent, call it here.
            raise FpdbParseError
        

        
        if len(self.pots) == 1: # (only use Total pot)
            return "Total pot $%.2f" % (self.total,)
        elif len(self.pots) == 2:
            return "Total pot $%.2f Main pot $%.2f. Side pot $%2.f." % (self.total, self.pots[0], self.pots[1])
        elif len(self.pots) == 3:
            return "Total pot $%.2f Main pot $%.2f. Side pot-1 $%2.2f. Side pot-2 $%.2f." % (self.total, self.pots[0], self.pots[1], self.pots[2])
        elif len(self.pots) == 0:
            # no small blind and walk in bb (hopefully)
            return "Total pot $%.2f" % (self.total,)
        else:
            return _("too many pots.. no small blind and walk in bb?. self.pots: %s" %(self.pots))
            # I don't know stars format for a walk in the bb when sb doesn't post.
            # The thing to do here is raise a Hand error like fpdb import does and file it into errors.txt
