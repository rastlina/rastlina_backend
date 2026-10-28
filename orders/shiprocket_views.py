"""
orders/shiprocket_views.py
Rastlina — Shiprocket API endpoints.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Order
from .shiprocket_service import check_serviceability, track_order


@api_view(["POST"])
@permission_classes([AllowAny])
def check_pincode_serviceability(request):
    pincode = request.data.get("pincode", "").strip()
    weight = float(request.data.get("weight", 0.5))

    if not pincode or len(pincode) != 6 or not pincode.isdigit():
        return Response({"error": "A valid 6-digit pincode is required."}, status=400)

    result = check_serviceability(pincode, weight=weight)

    if result["success"]:
        return Response({
            "serviceable": result["count"] > 0,
            "courier_count": result["count"],
            "couriers": [
                {
                    "name": c.get("courier_name"),
                    "etd": c.get("etd"),
                    "rate": c.get("rate"),
                }
                for c in result["couriers"][:5]
            ],
        })

    return Response({"serviceable": None, "error": result["error"]}, status=200)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def track_shipment_view(request, pk):
    try:
        order = Order.objects.get(pk=pk, user=request.user)
    except Order.DoesNotExist:
        return Response({"error": "Order not found."}, status=404)

    awb = getattr(order, "awb_code", None)
    if not awb:
        return Response({
            "tracked": False,
            "message": "Shipment not yet dispatched. Tracking will be available once your order is shipped.",
            "tracking_link": order.tracking_link or None,
        })

    result = track_order(order)

    if result["success"]:
        return Response({
            "tracked": True,
            "awb_code": awb,
            "tracking_link": order.tracking_link or f"https://shiprocket.co/tracking/{awb}",
            "tracking_data": result.get("tracking", {}),
        })

    return Response({
        "tracked": False,
        "message": "Could not fetch live tracking. Please use the tracking link.",
        "tracking_link": order.tracking_link or None,
    })
