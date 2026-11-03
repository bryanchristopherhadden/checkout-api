from concurrent import futures
from typing import NoReturn

import grpc

import checkout_pb2
import checkout_pb2_grpc
from commerce import (
    Cart,
    CartLine,
    Checkout,
    CommerceService,
    EmptyCartError,
    InvalidDiscountError,
    NotFoundError,
    OutOfStockError,
)


def _set_error(context: grpc.ServicerContext, error: Exception) -> NoReturn:
    if isinstance(error, NotFoundError):
        context.abort(grpc.StatusCode.NOT_FOUND, str(error))
    if isinstance(error, InvalidDiscountError):
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
    if isinstance(error, EmptyCartError):
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))
    if isinstance(error, OutOfStockError):
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))
    raise error


def _line_message(line: CartLine) -> checkout_pb2.CartLine:
    return checkout_pb2.CartLine(
        product_id=line.product_id,
        name=line.name,
        unit_price_cents=line.unit_price_cents,
        quantity=line.quantity,
        line_total_cents=line.line_total_cents,
    )


def _cart_message(cart: Cart) -> checkout_pb2.CartResponse:
    return checkout_pb2.CartResponse(
        cart_id=cart.cart_id,
        items=[_line_message(line) for line in cart.items],
        discount_code=cart.discount_code or "",
        subtotal_cents=cart.subtotal_cents,
        discount_cents=cart.discount_cents,
        total_cents=cart.total_cents,
    )


def _checkout_message(order: Checkout) -> checkout_pb2.CheckoutResponse:
    return checkout_pb2.CheckoutResponse(
        order_id=order.order_id,
        cart_id=order.cart_id,
        currency=order.currency,
        items=[_line_message(line) for line in order.items],
        subtotal_cents=order.subtotal_cents,
        discount_code=order.discount_code or "",
        discount_cents=order.discount_cents,
        total_cents=order.total_cents,
    )


class CheckoutCommandServicer(checkout_pb2_grpc.CheckoutCommandsServicer):
    def __init__(self, service: CommerceService) -> None:
        self.service = service

    def CreateCart(
        self, request: checkout_pb2.CreateCartRequest, context: grpc.ServicerContext
    ) -> checkout_pb2.CartResponse:
        return _cart_message(self.service.create_cart())

    def AddToCart(
        self, request: checkout_pb2.AddToCartRequest, context: grpc.ServicerContext
    ) -> checkout_pb2.CartResponse:
        if request.quantity <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be positive")
        try:
            return _cart_message(
                self.service.add_item(
                    request.cart_id, request.product_id, request.quantity
                )
            )
        except (NotFoundError, OutOfStockError) as error:
            _set_error(context, error)

    def RemoveFromCart(
        self,
        request: checkout_pb2.RemoveFromCartRequest,
        context: grpc.ServicerContext,
    ) -> checkout_pb2.CartResponse:
        try:
            return _cart_message(
                self.service.remove_item(request.cart_id, request.product_id)
            )
        except NotFoundError as error:
            _set_error(context, error)

    def ClearCart(
        self, request: checkout_pb2.CartRequest, context: grpc.ServicerContext
    ) -> checkout_pb2.CartResponse:
        try:
            return _cart_message(self.service.clear_cart(request.cart_id))
        except NotFoundError as error:
            _set_error(context, error)

    def ApplyDiscount(
        self,
        request: checkout_pb2.ApplyDiscountRequest,
        context: grpc.ServicerContext,
    ) -> checkout_pb2.CartResponse:
        try:
            return _cart_message(
                self.service.apply_discount(request.cart_id, request.code)
            )
        except (NotFoundError, InvalidDiscountError) as error:
            _set_error(context, error)

    def CheckoutCart(
        self, request: checkout_pb2.CartRequest, context: grpc.ServicerContext
    ) -> checkout_pb2.CheckoutResponse:
        try:
            return _checkout_message(self.service.checkout_cart(request.cart_id))
        except (NotFoundError, EmptyCartError, OutOfStockError) as error:
            _set_error(context, error)

    def CheckStock(
        self, request: checkout_pb2.CheckStockRequest, context: grpc.ServicerContext
    ) -> checkout_pb2.CheckStockResponse:
        try:
            return checkout_pb2.CheckStockResponse(
                product_id=request.product_id,
                available_quantity=self.service.check_stock(request.product_id),
            )
        except NotFoundError as error:
            _set_error(context, error)


def start_grpc_server(
    service: CommerceService, port: int
) -> tuple[grpc.Server, int]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    checkout_pb2_grpc.add_CheckoutCommandsServicer_to_server(
        CheckoutCommandServicer(service), server
    )
    bound_port = server.add_insecure_port(f"[::]:{port}")
    if bound_port == 0:
        raise RuntimeError(f"Could not bind gRPC server to port {port}")
    server.start()
    return server, bound_port
