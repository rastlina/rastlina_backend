from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory

from .models import (MainCategory, Category, Product, ProductVariant,
                     ProductImage, SizeOption, ColorOption, Review)
from .serializers import ProductListSerializer, ProductSearchSerializer
from .views import ProductListView


class CataloguePerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        main = MainCategory.objects.create(name='Plants', slug='plants')
        cls.category = Category.objects.create(name='Collection', slug='collection', main_category=main)
        cls.small = SizeOption.objects.create(name='Small', order=2)
        cls.medium = SizeOption.objects.create(name='Medium', order=1)
        cls.cream = ColorOption.objects.create(name='Cream', order=2, hex_code='#fefefe')
        cls.green = ColorOption.objects.create(name='Green', order=1, hex_code='#00ff00')
        cls.product = cls.make_product(0)

    @classmethod
    def make_product(cls, index):
        product = Product.objects.create(name=f'Plant {index}', slug=f'plant-{index}',
                                         sku=f'PERF-{index}', category=cls.category,
                                         price='199.00', original_price='399.00')
        for size, color, stock in [(cls.small, cls.cream, 3), (cls.small, cls.green, 0), (cls.medium, None, 0)]:
            ProductVariant.objects.create(product=product, size=size, color=color, stock=stock)
        ProductImage.objects.create(product=product, color=cls.cream, image='products/primary.webp', is_primary=True, order=2)
        ProductImage.objects.create(product=product, color=cls.green, image='products/other.webp', order=1)
        for rating in [3, 5]:
            Review.objects.create(product=product, user_name='Test', rating=rating, comment='Test review')
        return product

    def queryset(self):
        view = ProductListView()
        view.request = type('Request', (), {'query_params': {}})()
        return view.get_queryset()

    def test_serialization_uses_only_already_fetched_relations(self):
        product = self.queryset().get(pk=self.product.pk)
        with self.assertNumQueries(0):
            data = ProductListSerializer(product).data
        self.assertEqual(data['review_count'], 2)
        self.assertEqual(data['average_rating'], 4)
        self.assertEqual(data['available_sizes'], [{'id': self.medium.id, 'name': 'Medium'}, {'id': self.small.id, 'name': 'Small'}])
        self.assertEqual([color['name'] for color in data['available_colors']], ['Green', 'Cream'])
        self.assertTrue(data['in_stock'])
        self.assertEqual(data['images'][0]['color_name'], 'Green')

    def test_query_count_does_not_grow_with_catalogue_size(self):
        request = APIRequestFactory().get('/products/?ordering=price')
        with CaptureQueriesContext(connection) as small:
            first = ProductListView.as_view()(request)
        for index in range(1, 16):
            self.make_product(index)
        with CaptureQueriesContext(connection) as large:
            response = ProductListView.as_view()(request)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 16)
        self.assertEqual(len(small), len(large), f'Query count grew from {len(small)} to {len(large)}')
        self.assertLessEqual(len(large), 10)
        print(f'Catalogue queries: {len(small)} for 1 product; {len(large)} for 16 products')

    def test_unprefetched_serialization_retains_the_same_values_and_live_stock(self):
        original = ProductListSerializer(Product.objects.get(pk=self.product.pk)).data
        optimized = ProductListSerializer(self.queryset().get(pk=self.product.pk)).data
        self.assertEqual(original, optimized)
        ProductVariant.objects.filter(product=self.product).update(stock=0)
        self.assertFalse(ProductListSerializer(self.queryset().get(pk=self.product.pk)).data['in_stock'])

    def test_search_uses_prefetched_primary_image_without_new_queries(self):
        product = self.queryset().get(pk=self.product.pk)
        with self.assertNumQueries(0):
            data = ProductSearchSerializer(product).data
        self.assertEqual(data['image'], '/media/products/primary.webp')

    def test_public_list_supports_gzip_without_changing_the_response(self):
        import gzip
        import json
        request = APIRequestFactory().get('/products/', HTTP_ACCEPT_ENCODING='gzip')
        response = ProductListView.as_view()(request)
        response.render()
        self.assertEqual(response['Content-Encoding'], 'gzip')
        data = json.loads(gzip.decompress(response.content))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['price'], '199.00')
        self.assertIn('Accept-Encoding', response['Vary'])
