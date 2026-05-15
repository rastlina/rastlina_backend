from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import traceback

class ContactEmailView(APIView):
    def post(self, request):
        data = request.data
        context = {
            'name': data.get('name'),
            'email': data.get('email'),
            'phone': data.get('phone'),
            'issue_type': data.get('issue_type', 'Bulk Inquiry'),
            'message': data.get('message'),
        }

        subject = f"New Rastlina Lead: {context['issue_type']} from {context['name']}"
        
        try:
            html_content = render_to_string('mails/contact_email.html', context)
            text_content = strip_tags(html_content)

            msg = EmailMultiAlternatives(
                subject,
                text_content,
                settings.DEFAULT_FROM_EMAIL,
                [settings.ADMIN_EMAIL]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            return Response({"detail": "Inquiry sent successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            print("--- SMTP/MAIL ERROR ---")
            print(traceback.format_exc())
            return Response(
                {"error": "Failed to send email. Please check server logs."}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )