# sqs-orchestrator

High-level library for asynchronous communication using Amazon SQS. Enables easy building of message producers that expect responses, as well as consumers that send responses.

## Features

- **Asynchronous communication** between microservices
- **One-way messaging** for fire-and-forget operations
- **Two-way messaging** (request-response) with automatic reply queue management
- **Automatic message routing** to reply queues
- **Built-in timeout handling** for response waiting
- **Memory-based response storage** for fast retrieval

## Architecture

This library is based on the [amazon-sqs-java-temporary-queues-client](https://github.com/awslabs/amazon-sqs-java-temporary-queues-client) but does not use the concept of Virtual Queues. Instead:
- Each producer creates its own temporary reply queue
- Responses are stored in memory for fast access
- Automatic cleanup of temporary resources
- Built-in heartbeat mechanism to keep queues alive

## Installation

```bash
pip install python-sqs-client
```

## Quick Start

### Prerequisites

```python
import multiprocessing
multiprocessing.set_start_method('fork', force=True)  # Required for macOS/Linux
```

### Configuration

```python
CONFIG = {
    "access_key": "your-aws-access-key",
    "secret_key": "your-aws-secret-key",
    "region_name": "us-east-1",
    "queue_url": "https://sqs.us-east-1.amazonaws.com/account/your-queue"
}
```

## Usage Examples

### Producer (Request Sender)

```python
import json
import uuid
from datetime import datetime
from sqs_client.factories import ReplyQueueFactory, PublisherFactory
from sqs_client.message import RequestMessage
from sqs_client.exceptions import ReplyTimeout

class TaskSender:
    def __init__(self, config):
        # Create temporary reply queue
        self.reply_queue = ReplyQueueFactory(
            name=f'reply_queue_{uuid.uuid4().hex[:8]}_',
            access_key=config['access_key'],
            secret_key=config['secret_key'],
            region_name=config['region_name']
        ).build()
        
        # Create publisher
        self.publisher = PublisherFactory(
            access_key=config['access_key'],
            secret_key=config['secret_key'],
            region_name=config['region_name']
        ).build()
    
    def send_request(self, task_data, timeout=60):
        task_id = str(uuid.uuid4())
        
        message_body = {
            "task_id": task_id,
            "data": task_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Create request message with reply queue info
        message = RequestMessage(
            body=json.dumps(message_body),
            queue_url=config['queue_url'],
            reply_queue=self.reply_queue
        )
        
        # Send message
        self.publisher.send_message(message)
        
        try:
            # Wait for response
            response = message.get_response(timeout=timeout)
            return json.loads(response.body)
        except ReplyTimeout:
            return None
    
    def cleanup(self):
        """Important: Always cleanup to remove temporary queues"""
        if self.reply_queue:
            self.reply_queue.remove_queue()

# Usage
sender = TaskSender(CONFIG)
try:
    result = sender.send_request({"operation": "process_data", "value": 42})
    print(f"Result: {result}")
finally:
    sender.cleanup()
```

### Consumer (Message Processor)

```python
import json
from sqs_client.contracts import MessageHandler
from sqs_client.subscriber import MessagePoller
from sqs_client.factories import SubscriberFactory, PublisherFactory

class ProcessingHandler(MessageHandler):
    def process_message(self, message):
        """Process incoming message and return response"""
        try:
            # Parse request
            request_data = json.loads(message.body)
            task_id = request_data.get('task_id')
            data = request_data.get('data', {})
            
            # Your processing logic here
            result = self.perform_processing(data)
            
            # Prepare response
            response = {
                "task_id": task_id,
                "status": "completed",
                "result": result
            }
            
            return json.dumps(response)
            
        except Exception as e:
            # Return error response
            error_response = {
                "task_id": request_data.get('task_id', 'unknown'),
                "status": "error",
                "error": str(e)
            }
            return json.dumps(error_response)
    
    def perform_processing(self, data):
        """Your actual business logic goes here"""
        operation = data.get('operation', 'default')
        if operation == 'process_data':
            return {"processed_value": data.get('value', 0) * 2}
        return {"message": f"Processed {operation}"}

# Setup consumer
subscriber = SubscriberFactory(
    access_key=CONFIG['access_key'],
    secret_key=CONFIG['secret_key'],
    region_name=CONFIG['region_name'],
    queue_url=CONFIG['queue_url']
).build()

publisher = PublisherFactory(
    access_key=CONFIG['access_key'],
    secret_key=CONFIG['secret_key'],
    region_name=CONFIG['region_name']
).build()

# Start processing
poller = MessagePoller(
    handler=ProcessingHandler(),
    subscriber=subscriber,
    publisher=publisher
)

poller.start()  # Blocks until interrupted
```

## Advanced Features

### Custom Message Attributes

```python
message = RequestMessage(
    body=json.dumps(data),
    queue_url=queue_url,
    reply_queue=reply_queue,
    message_attributes={
        'Priority': {'StringValue': 'HIGH', 'DataType': 'String'},
        'Source': {'StringValue': 'WebAPI', 'DataType': 'String'}
    }
)
```

### Error Handling

```python
from sqs_client.exceptions import ReplyTimeout

try:
    response = message.get_response(timeout=30)
except ReplyTimeout:
    print("Request timed out")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Batch Operations

```python
messages = []
for i in range(10):
    message = RequestMessage(
        body=json.dumps({'batch_item': i}),
        queue_url=queue_url,
        reply_queue=reply_queue
    )
    publisher.send_message(message)
    messages.append(message)

# Wait for all responses
results = []
for message in messages:
    try:
        response = message.get_response(timeout=60)
        results.append(json.loads(response.body))
    except ReplyTimeout:
        results.append(None)
```

## Known Issues & Solutions

### 1. Multiprocessing Pickle Error (macOS/Linux)

**Issue**: `Can't pickle <class 'boto3.resources.factory.sqs.Queue'>`

**Solution**: Add this at the top of your script:
```python
import multiprocessing
multiprocessing.set_start_method('fork', force=True)
```

### 2. Sweeper Queue Cleanup

**Issue**: FIFO sweeper queues (e.g., `reply_queue_abc123_sweeper.fifo`) are not automatically cleaned up.

**Solution**: Manual cleanup in your TaskSender class:
```python
import boto3

class TaskSender:
    def __init__(self, config):
        # ... existing initialization ...
        
        # Add SQS client for manual cleanup
        self.sqs_client = boto3.client('sqs', **aws_credentials)
    
    def cleanup(self):
        reply_queue_name = None
        if self.reply_queue:
            reply_queue_name = self.reply_queue.get_name()
            self.reply_queue.remove_queue()
            
            # Manual sweeper cleanup
            self._cleanup_sweeper_queue(reply_queue_name)
    
    def _cleanup_sweeper_queue(self, reply_queue_name):
        if not reply_queue_name:
            return
            
        # Extract prefix and construct sweeper name
        parts = reply_queue_name.split('_')
        if len(parts) >= 3:
            prefix = '_'.join(parts[:3])
            sweeper_name = f"{prefix}sweeper.fifo"
            
            try:
                response = self.sqs_client.get_queue_url(QueueName=sweeper_name)
                self.sqs_client.delete_queue(QueueUrl=response['QueueUrl'])
                print(f"Cleaned up sweeper queue: {sweeper_name}")
            except self.sqs_client.exceptions.QueueDoesNotExist:
                pass  # Already deleted
```

### 3. Resource Management

Always use try-finally blocks or context managers:

```python
def safe_request_response():
    sender = TaskSender(config)
    try:
        return sender.send_request(data)
    finally:
        sender.cleanup()
```

## Configuration Options

### Reply Queue Factory

```python
reply_queue = ReplyQueueFactory(
    name='custom_reply_',                    # Queue name prefix
    access_key='aws_access_key',
    secret_key='aws_secret_key', 
    region_name='us-east-1',
    message_retention_period=60,             # Seconds
    seconds_before_cleaning=20,              # Message cleanup interval
    num_messages_before_cleaning=200,        # Message count threshold
    heartbeat_interval_seconds=300           # Heartbeat frequency
).build()
```

### Publisher Factory

```python
publisher = PublisherFactory(
    access_key='aws_access_key',
    secret_key='aws_secret_key',
    region_name='us-east-1'
).build()
```

### Subscriber Factory

```python
subscriber = SubscriberFactory(
    access_key='aws_access_key',
    secret_key='aws_secret_key',
    region_name='us-east-1',
    queue_url='queue_url'
).build()
```

## Best Practices

1. **Always cleanup**: Use try-finally blocks to ensure reply queues are deleted
2. **Set appropriate timeouts**: Match your processing time requirements
3. **Handle timeouts gracefully**: Implement retry logic if needed
4. **Monitor queue metrics**: Watch for stuck messages or growing queues
5. **Use meaningful task IDs**: Include correlation IDs for tracing
6. **Implement dead letter queues**: For your main processing queues
7. **Test error scenarios**: Ensure error responses are handled correctly

## Troubleshooting

### Queue Not Found Errors
- Verify AWS credentials and permissions
- Check region configuration
- Ensure queue URLs are correct

### Messages Not Received
- Verify queue visibility timeout settings
- Check message retention periods
- Confirm subscriber is polling correct queue

### Memory Issues
- Monitor message dictionary growth in reply queues
- Implement message cleanup strategies
- Consider processing limits

### Performance Issues
- Adjust heartbeat intervals
- Tune message batch sizes  
- Monitor AWS SQS throttling limits

## Production Considerations

- **Monitoring**: Implement CloudWatch metrics for queue depth, age, errors
- **Alerting**: Set up alarms for stuck messages or high error rates  
- **Scaling**: Consider multiple consumer instances for high throughput
- **Security**: Use IAM roles instead of access keys when possible
- **Cost**: Monitor SQS costs, especially for high-frequency heartbeats