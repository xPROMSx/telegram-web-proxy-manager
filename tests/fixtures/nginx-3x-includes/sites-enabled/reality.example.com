server {
    server_tokens off;
    server_name reality.example.com;
    listen 127.0.0.1:9443 ssl http2 proxy_protocol;
    real_ip_header proxy_protocol;
    set_real_ip_from 127.0.0.1;

    index index.html index.htm index.php;
    root /var/www/html/;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!eNULL:!MD5:!DES:!RC4:!ADH:!SSLv3:!EXP:!PSK:!DSS;
    ssl_certificate     /etc/letsencrypt/live/reality.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/reality.example.com/privkey.pem;
    if ($host !~* ^(.+\.)?reality.example.com$)            { return 444; }
    if ($scheme ~* https)                                  { set $safe 1; }
    if ($ssl_server_name !~* ^(.+\.)?reality.example.com$) { set $safe "${safe}0"; }
    if ($safe = 10)                                        { return 444; }
    if ($request_uri ~ "(\"|'|`|~|,|:|;|%|\$|&&|\?\?|0x00|0X00|\||\|\{|\}|\[|\]|<|>|\.\.\.|\.\.\/|\/\/\/)") { set $hack 1; }
    error_page 400 401 402 403 500 501 502 503 504 =404 /404;
    proxy_intercept_errors on;

    include snippets/includes.conf;
}
