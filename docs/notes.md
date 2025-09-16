
### Notes:

````
rabbitmqctl set_topic_permissions -p my-vhost user amq.topic "*.{client_id}-." "*.{client_id}-.*"
````
RABBITMQ_CONFIG_FILE=/path/to/a/custom/location/rabbitmq/my.conf

debian/ubuntu - /etc/rabbitmq/rabbitmq.conf

### Alembic

````
 alembic revision --autogenerate -m "comment"
 alembic upgrade head
````


