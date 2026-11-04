# Rate limiting zones (http context)
limit_req_zone  $binary_remote_addr zone=diag_api:10m  rate=6r/m;
limit_req_zone  $binary_remote_addr zone=diag_page:10m rate=30r/m;
limit_conn_zone $binary_remote_addr zone=per_ip:10m;

# Diagnostics access: cookie issued by the SSO bridge after panel login
# Exact regex avoids a 40-byte hash entry on CPUs with 32-byte map buckets.
map $cookie_diag_key $diag_auth {
    "~*\Afixture-placeholder-not-a-credential\z" 1;
    default          0;
}

server {
    server_tokens off;
    server_name panel.example.com;
    listen 127.0.0.1:7443 ssl http2 proxy_protocol;

    index index.html index.htm index.php;
    root /var/www/html/;
    real_ip_header proxy_protocol;
    set_real_ip_from 127.0.0.1;
    # This vhost listens on 7443 behind the SNI stream (public port 443). Without
    # this, nginx bakes :7443 into redirect Location headers (return/error_page),
    # so browsers get sent to an unreachable port. Keep redirects relative.
    absolute_redirect off;
    # Larger h2 preread window improves single-stream upload throughput
    http2_max_concurrent_streams 256;
    http2_body_preread_size 128k;
    client_body_buffer_size 512k;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!eNULL:!MD5:!DES:!RC4:!ADH:!SSLv3:!EXP:!PSK:!DSS;
    ssl_certificate     /etc/letsencrypt/live/panel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/panel.example.com/privkey.pem;
    if ($host !~* ^(.+\.)?panel.example.com$)            { return 444; }
    if ($scheme ~* https)                          { set $safe 1; }
    if ($ssl_server_name !~* ^(.+\.)?panel.example.com$) { set $safe "${safe}0"; }
    if ($safe = 10)                                { return 444; }
    if ($request_uri ~ "(\"|'|`|~|,|:|;|%|\$|&&|\?\?|0x00|0X00|\||\|\{|\}|\[|\]|<|>|\.\.\.|\.\.\/|\/\/\/)") { set $hack 1; }
    error_page 400 401 402 403 500 501 502 503 504 =404 /404;
    proxy_intercept_errors on;

    location /panel/ {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass https://127.0.0.1:2053;
    }
    location /panel {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass https://127.0.0.1:2053;
    }

    # ── Diagnostics SSO bridge ───────────────────────────────────────────────
    # Lives under the panel path so the browser attaches the 3x-ui session
    # cookie (its Path is scoped to the panel base path). Valid panel session
    # → issue the diag cookie and redirect; otherwise → panel login page.
    # NOTE: auth_request runs in the access phase; a plain "return" here would
    # skip it (rewrite phase), hence the try_files → named-location hop.
    location = /panel/diag {
        auth_request /__diag_auth;
        # Named location (not "=302 /uri") so the deny path emits a real Location
        # header; an internal-redirect error_page returns a 302 with no Location.
        error_page 401 403 = @diag_login;
        try_files /__nonexistent @diag_sso_ok;
    }
    location @diag_login {
        return 302 /panel/;
    }
    location @diag_sso_ok {
        add_header Set-Cookie "diag_key=fixture-placeholder-not-a-credential; Path=/diagnostics/; Secure; HttpOnly; SameSite=Lax; Max-Age=604800";
        return 302 /diagnostics/;
    }
    location = /__diag_auth {
        internal;
        proxy_pass https://127.0.0.1:2053/panel/panel/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        # 3x-ui answers AJAX requests with 401 instead of a login redirect
        proxy_set_header X-Requested-With XMLHttpRequest;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        # auth_request emits a raw 500 to the browser if the subrequest returns
        # anything other than 2xx / 401 / 403 (a login 302, or a 502 when the
        # panel's HTTPS cert is missing). Coerce every such status to a 401 deny
        # so the main location redirects to the panel login instead of 500ing.
        # 401/403 must be listed too, else the server-level "error_page 401 =404"
        # hijacks a genuine deny into a 404 (which auth_request then 500s on).
        proxy_intercept_errors on;
        error_page 300 301 302 303 304 305 307 308 400 401 402 403 404 405 500 501 502 503 504 =401 @diag_denied;
    }
    location @diag_denied { return 401; }

    # ── Network diagnostics page ─────────────────────────────────────────────
    # No diag cookie yet → bounce through the SSO bridge, which checks the panel
    # session and mints the cookie, so a bookmarked diag link "just works" once
    # you're logged into the panel. (Only the HTML page redirects; the API/asset
    # sub-locations below stay 404 without the cookie.)
    location ^~ /diagnostics/ {
        if ($diag_auth = 0) { return 302 /panel/diag; }
        limit_req  zone=diag_page burst=10 nodelay;
        limit_conn per_ip 5;
        alias /var/www/diagnostics/;
        index index.html;
        try_files $uri $uri/ /index.html;
        add_header Set-Cookie "diag_key=fixture-placeholder-not-a-credential; Path=/diagnostics/; Secure; HttpOnly; SameSite=Lax; Max-Age=604800" always;
        add_header Cache-Control "no-store" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }

    # ── Diagnostics MTR API ──────────────────────────────────────────────────
    location ^~ /diagnostics/api/mtr {
        if ($diag_auth = 0) { return 404; }
        limit_req  zone=diag_api burst=2 nodelay;
        limit_conn per_ip 2;
        proxy_pass         http://127.0.0.1:9080/api/mtr;
        proxy_http_version 1.1;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        # Let the backend's JSON error bodies through; the server-level
        # "proxy_intercept_errors on" would otherwise rewrite a 500 into an HTML
        # 404 and break the frontend's response.json() parse.
        proxy_intercept_errors off;
    }

    # ── LibreSpeed upload sink ───────────────────────────────────────────────
    # No limit_req: librespeed fires many short POSTs (parallel streams).
    # proxy_request_buffering off = client sees true network backpressure.
    location ^~ /diagnostics/api/st/up {
        if ($diag_auth = 0) { return 404; }
        access_log              off;
        limit_conn              per_ip 8;
        proxy_pass              http://127.0.0.1:9080/api/st/up;
        proxy_http_version      1.1;
        proxy_set_header        X-Real-IP       $remote_addr;
        proxy_request_buffering off;
        client_max_body_size    64m;
        proxy_read_timeout      60s;
        proxy_send_timeout      60s;
        add_header              Cache-Control "no-store" always;
    }

    # ── LibreSpeed ping endpoint (answered by nginx, no backend hop) ─────────
    location = /diagnostics/api/st/ping {
        if ($diag_auth = 0) { return 404; }
        access_log off;
        limit_conn per_ip 8;
        add_header Cache-Control "no-store" always;
        default_type text/plain;
        return 200 "";
    }

    # ── LibreSpeed client IP ─────────────────────────────────────────────────
    location = /diagnostics/api/st/getip {
        if ($diag_auth = 0) { return 404; }
        proxy_pass          http://127.0.0.1:9080/api/st/getip;
        proxy_http_version  1.1;
        proxy_set_header    X-Real-IP $remote_addr;
        add_header          Cache-Control "no-store" always;
    }

    # ── Download test files ──────────────────────────────────────────────────
    location ^~ /diagnostics/testfiles/ {
        if ($diag_auth = 0) { return 404; }
        alias      /var/www/diagnostics/testfiles/;
        access_log off;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Content-Disposition "attachment" always;
    }

    # ── Clash YAML generator — internal, proxied here by rewrite from sub_path ────
    location = /__clash_api {
        internal;
        access_log off;
        error_log /dev/null crit;
        error_page 404 =404 @subscription_error;
        proxy_pass          http://127.0.0.1:9080/api/clash$is_args$args;
        proxy_http_version  1.1;
        proxy_set_header    X-Real-IP $remote_addr;
    }

    include snippets/x-ui-auto-optional/*.conf;
    include snippets/includes.conf;
}
