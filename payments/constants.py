"""
Order workflow strings shared with checkout.

``ORDER_STATUS_PAYMENT_PENDING`` is set when an order is created from the cart and awaits hosted checkout.
After successful payment, fulfillment moves the order toward ``ORDER_STATUS_AWAITING_PRODUCER`` (``pending``).
"""

ORDER_STATUS_PAYMENT_PENDING = "payment_pending"
ORDER_STATUS_AWAITING_PRODUCER = "pending"
