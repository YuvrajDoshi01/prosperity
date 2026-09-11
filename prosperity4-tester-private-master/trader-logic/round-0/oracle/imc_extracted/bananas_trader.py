from datamodel import OrderDepth, TradingState, Order


class Trader:
    banana_markets = {}

    def run(self, state: TradingState):
        result = {}
        quote_volume = 5
        best_ask = 0
        best_ask_amount = 0
        best_bid = 0
        best_bid_amount = 0

        for product in state.order_depths:
            print('product: ' + product)
            orders: list[Order] = []

            if product == 'PEARLS':
                order_depth: OrderDepth = state.order_depths[product]
                acceptable_price = 10000  # Participant should calculate this value

                if len(order_depth.sell_orders) != 0:
                    best_ask, best_ask_amount = list(sorted(order_depth.sell_orders.items()))[0]
                if len(order_depth.buy_orders) != 0:
                    best_bid, best_bid_amount = list(sorted(order_depth.buy_orders.items(), reverse=True))[0]

                if len(order_depth.sell_orders) != 0:
                    print('if best_ask not None')
                    if int(best_ask) < acceptable_price:
                        orders.append(Order(product, best_ask, -best_ask_amount))
                        print('I buy')
                    if int(best_ask - 1) > acceptable_price:
                        ask_price = int(best_ask - 1)
                        orders.append(Order(product, ask_price, -quote_volume))

                if len(order_depth.buy_orders) != 0:
                    print('if best_bid not None')
                    if int(best_bid) > acceptable_price:
                        orders.append(Order(product, best_bid, -best_bid_amount))
                        print('I sell')
                    if int(best_bid + 1) < acceptable_price:
                        bid_price = int(best_bid + 1)
                        orders.append(Order(product, bid_price, quote_volume))

                result[product] = orders

            if product == 'BANANAS':
                order_depth: OrderDepth = state.order_depths[product]
                len_memory = 7

                if len(order_depth.sell_orders) != 0:
                    best_ask, best_ask_amount = list(sorted(order_depth.sell_orders.items()))[0]
                if len(order_depth.buy_orders) != 0:
                    best_bid, best_bid_amount = list(sorted(order_depth.buy_orders.items(), reverse=True))[0]

                if not self.banana_markets:
                    self.banana_markets = {
                        'last_bids': [],
                        'last_offers': [],
                        'ask': [],
                        'bid': []
                    }

                if len(order_depth.sell_orders) != 0:
                    best_ask, best_ask_amount = list(sorted(order_depth.sell_orders.items()))[0]
                    self.banana_markets['ask'].append(best_ask)
                    if len(self.banana_markets['ask']) > len_memory:
                        self.banana_markets['ask'].pop(0)

                if len(order_depth.buy_orders) != 0:
                    best_bid, best_bid_amount = list(sorted(order_depth.buy_orders.items(), reverse=True))[0]
                    self.banana_markets['bid'].append(best_bid)
                    if len(self.banana_markets['bid']) > len_memory:
                        self.banana_markets['bid'].pop(0)

                if all([len(self.banana_markets[s]) != 0 for s in ['bid', 'ask']]):
                    banana_valuation = 0.5 * sum([sum(self.banana_markets[s]) / len(self.banana_markets[s]) for s in ['bid', 'ask']])

                    if best_ask:
                        if best_ask < banana_valuation:
                            orders.append(Order(product, best_ask, -best_ask_amount))
                        if best_ask - 1 > banana_valuation:
                            orders.append(Order(product, int(best_ask - 1), -quote_volume))
                        if best_ask > banana_valuation:
                            orders.append(Order(product, int(best_ask), -quote_volume))

                    if best_bid:
                        if best_bid > banana_valuation:
                            orders.append(Order(product, best_bid, -best_bid_amount))
                        if best_bid + 1 < banana_valuation:
                            orders.append(Order(product, int(best_bid + 1), quote_volume))
                        if best_bid < banana_valuation:
                            orders.append(Order(product, int(best_bid), quote_volume))

                result[product] = orders

            cocos = ['COCONUTS', 'PINA_COLADAS']
            if product in cocos:
                bbos = {p: {'BID': None, 'ASK': None} for p in cocos}
                for p in bbos:
                    if len(state.order_depths[p].buy_orders) != 0:
                        bbos[p]['BID'] = list(sorted(state.order_depths[p].buy_orders.items(), reverse=True))[0]
                    if len(state.order_depths[p].sell_orders) != 0:
                        bbos[p]['ASK'] = list(sorted(state.order_depths[p].sell_orders.items()))[0]

                if (bbos['COCONUTS']['ASK'] is not None) and (bbos['PINA_COLADAS']['BID'] is not None):
                    if 2 * bbos['COCONUTS']['ASK'][0] < bbos['PINA_COLADAS']['BID'][0]:
                        orders.append(Order('COCONUTS', bbos['COCONUTS']['ASK'][0], -bbos['COCONUTS']['ASK'][1]))
                        orders.append(Order('PINA_COLADAS', bbos['PINA_COLADAS']['BID'][0], -bbos['PINA_COLADAS']['BID'][1]))

                if (bbos['COCONUTS']['BID'] is not None) and (bbos['PINA_COLADAS']['ASK'] is not None):
                    if 2 * bbos['COCONUTS']['BID'][0] > bbos['PINA_COLADAS']['ASK'][0]:
                        orders.append(Order('COCONUTS', bbos['COCONUTS']['BID'][0], -bbos['COCONUTS']['BID'][1]))
                        orders.append(Order('PINA_COLADAS', bbos['PINA_COLADAS']['ASK'][0], -bbos['PINA_COLADAS']['ASK'][1]))

                result[product] = orders

        return result
