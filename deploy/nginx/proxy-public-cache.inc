# Included in the public locations: cache what the API allows, serve stale copies while refreshing.
proxy_cache public_cache;
proxy_cache_key $scheme$request_method$host$request_uri;
proxy_cache_methods GET HEAD;
proxy_cache_lock on;
proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
proxy_cache_background_update on;
add_header X-Cache-Status $upstream_cache_status always;
