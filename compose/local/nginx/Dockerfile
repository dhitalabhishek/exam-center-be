FROM docker.io/nginx:1.17.8-alpine
COPY ./compose/local/nginx/default.conf /etc/nginx/conf.d/default.conf

# # Install OpenSSL, create SSL directories and generate certificate
# RUN apk add --no-cache openssl && \
#     mkdir -p /etc/ssl/private && \
#     # Create a better cert config
#     cat > /tmp/cert.conf <<EOF
#     [req]
#     distinguished_name = req_distinguished_name
#     req_extensions = v3_req
#     prompt = no

#     [req_distinguished_name]
#     C = US
#     ST = State
#     L = City
#     O = Organization
#     CN = localhost

#     [v3_req]
#     keyUsage = keyEncipherment, dataEncipherment
#     extendedKeyUsage = serverAuth
#     subjectAltName = @alt_names

#     [alt_names]
#     DNS.1 = localhost
#     DNS.2 = *.localhost
#     DNS.3 = 127.0.0.1.nip.io
#     DNS.4 = *.127.0.0.1.nip.io
#     IP.1 = 127.0.0.1
#     IP.2 = 0.0.0.0
#     IP.3 = 192.168.254.143
#     IP.4 = 10.10.0.101
#     EOF
#     # Generate new certificate
#     openssl req -x509 -nodes -days 36500 -newkey rsa:2048 \
#     -keyout /etc/ssl/private/nginx-selfsigned.key \
#     -out /etc/ssl/certs/nginx-selfsigned.crt \
#     -config /tmp/cert.conf -extensions v3_req && \
#     rm /tmp/cert.conf