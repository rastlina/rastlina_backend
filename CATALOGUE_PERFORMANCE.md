# Catalogue loading — 25 October 2026

ProductListView already prefetched variants and reviews, but serializer methods
used `filter()`, `values()` and `aggregate()` on related managers. These operations
issued fresh queries for every product rather than reading the fetched objects.
Image colour details also lacked prefetching on list/related/home responses.

The serializer now uses prefetched objects when available and keeps the existing
database-query fallback for unprefetched callers. Ratings, size/colour ordering,
stock, images, filters and response fields are retained. Homepage product lists
also prefetch reviews, and search reads the fetched primary image.

The five public product/list/home/search views support Django's standard
`gzip_page` compression when requested. Other endpoints and settings are unchanged.
No database migration, data update or persistent caching is required.

## Reproduction

Run with Django 5.2.13 and DRF 3.17.1:

```
python manage.py test store.test_catalogue_performance --settings=core.test_settings
```

The isolated test settings use an in-memory database and no production secrets.

- Before: 13 queries for one product; 103 queries for 16 products.
- After: 8 queries for one product; 8 queries for 16 products.
- Once relations are fetched, product serialization issues zero extra queries.
- Five tests pass, covering bounded queries, response equivalence, current stock,
  ordered/deduplicated sizes and colours, ratings, primary images and gzip output.

The Django guidance on chained methods bypassing prefetched results is documented
at https://docs.djangoproject.com/en/5.2/ref/models/querysets/#prefetch-related.

## Release verification

Deployment uses the existing GitHub-main workflow. Verify the live products API
still returns every active product in the requested order and advertises gzip
when requested. Compare response timings and rerun mobile/desktop PageSpeed.
