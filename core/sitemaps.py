from xml.etree.ElementTree import Element, SubElement, tostring

from django.http import HttpResponse
from django.utils import timezone

from store.models import Product


SITE_URL = 'https://www.rastlina.com'


def sitemap(request):
    """Expose a crawlable, automatically updated sitemap for the storefront."""
    urlset = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')

    static_pages = (
        ('/', 'weekly', '1.0'),
        ('/shop', 'daily', '0.9'),
        ('/bulk', 'monthly', '0.5'),
        ('/privacy-policy', 'yearly', '0.2'),
        ('/terms-and-conditions', 'yearly', '0.2'),
        ('/shipping-policy', 'yearly', '0.3'),
        ('/returns-refund-policy', 'yearly', '0.3'),
        ('/replacement-policy', 'yearly', '0.3'),
        ('/blog/1', 'monthly', '0.6'),
        ('/blog/2', 'monthly', '0.6'),
        ('/blog/3', 'monthly', '0.6'),
    )

    for path, changefreq, priority in static_pages:
        url = SubElement(urlset, 'url')
        SubElement(url, 'loc').text = f'{SITE_URL}{path}'
        SubElement(url, 'changefreq').text = changefreq
        SubElement(url, 'priority').text = priority

    for product in Product.objects.filter(is_active=True).only('slug', 'updated_at'):
        url = SubElement(urlset, 'url')
        SubElement(url, 'loc').text = f'{SITE_URL}/product/{product.slug}'
        SubElement(url, 'lastmod').text = timezone.localtime(product.updated_at).date().isoformat()
        SubElement(url, 'changefreq').text = 'weekly'
        SubElement(url, 'priority').text = '0.8'

    xml = tostring(urlset, encoding='utf-8', xml_declaration=True)
    return HttpResponse(xml, content_type='application/xml; charset=utf-8')
