from datamodel import OrderDepth, UserId, TradingState, Order
import string


class Trader:
    def run(self, state: TradingState):
        result = {}
        for product in state.order_depths:
            if product == 'MAGNIFICENT_MACARONS':
                extendedObservation = state.observations.conversionObservations[product]
                transportfees = extendedObservation.transportFees
                exportfees = extendedObservation.exportTariff
                importfees = extendedObservation.importTariff
                acceptable_buy_price = extendedObservation.bidPrice - (transportfees + exportfees)
                acceptable_sell_price = extendedObservation.askPrice + (transportfees + importfees)

                order_depth: OrderDepth = state.order_depths[product]
                orders: list[Order] = []

                if len(order_depth.sell_orders) != 0:
                    best_ask, best_ask_amount = list(sorted(order_depth.sell_orders.items()))[0]
                    if int(best_ask) < acceptable_buy_price:
                        print("BUY", str(-best_ask_amount) + "x", best_ask)
                        orders.append(Order(product, best_ask, -best_ask_amount))

                if len(order_depth.buy_orders) != 0:
                    best_bid, best_bid_amount = list(sorted(order_depth.buy_orders.items(), reverse=True))[0]
                    if int(best_bid) > acceptable_sell_price:
                        print("SELL", str(best_bid_amount) + "x", best_bid)
                        orders.append(Order(product, best_bid, -best_bid_amount))

                result[product] = orders

        traderData = "SAMPLE"
        conversion = 0
        if state.position.get('MAGNIFICENT_MACARONS') != None:
            conversion = -(state.position.get('MAGNIFICENT_MACARONS') + 30)
            print("Conversion done for " + str(conversion) + " items")
        return result, conversion, traderData
