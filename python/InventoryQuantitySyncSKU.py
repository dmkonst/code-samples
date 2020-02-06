from botocore.vendored import requests
import json, os, boto3, uuid
import time
def event_handler(event, event_id, trace_id):
    dynamodb = boto3.resource('dynamodb').Table("events")
    s3 = boto3.resource('s3')
    with open("/tmp/event", "w") as f: 
        f.write(json.dumps(event))
    s3.Bucket(os.environ["EventsBucket"]).upload_file('/tmp/event', event_id)
    dynamodb_item = {
        "event_id":     event_id,
        "lambda":       "InventoryQuantitySyncSKU",
        "process":      "InventoryQuantitySync",
        "status":       "In Progress. Polling BrightPearl",
        "trace_id":     trace_id,
        "timestamp":    int(time.time())
    }
    dynamodb.put_item(Item=dynamodb_item)
def is_failed(event_id, trace_id):
    dynamodb = boto3.resource('dynamodb').Table("events")
    dynamodb_item = {
    "event_id":     event_id,
    "lambda":       "InventoryQuantitySyncSKU",
    "process":      "InventoryQuantitySync",
    "status":       "Failed. Check logs or resubmit event",
    "trace_id":     trace_id,
    "timestamp":    int(time.time())
    }
    dynamodb.put_item(Item=dynamodb_item)
    return
def lambda_handler(event, context):
    ids={}
    ids_array=[]
    sku={}
    result = {}
    products = {}
    DynamoDBSearchKeys=[]
    query=""
    productIDs2BeSynced={"products": {}}
    sqs = boto3.client('sqs')
    for record in event['Records']:
        body=json.loads(record["body"])
        print (body)            
        event_id = str(uuid.uuid4())
        trace_id = str(json.loads(record["body"])['trace_id'])
        event_body = {
            "Records": [record]
        }
        event_handler(event_body, event_id, trace_id)
        ids[str(body['id'])]={"trace_id": trace_id, "event_id": event_id}
    for key, value in ids.items():
        ids_array.append(int(key))
    ids_array.sort()
    product_ids=",".join(str(v) for v in ids_array)
    print (product_ids)
    headers={"brightpearl-staff-token": os.environ["brightpearl_staff_token"], 
            "brightpearl-app-ref": os.environ["brightpearl_app_ref"]
            }
    product_availability = requests.get("%s%s%s" % (os.environ["bp_url"], "warehouse-service/product-availability/", product_ids), headers=headers)
    if product_availability.status_code == 200:
        product_availability=json.loads(product_availability.content)['response']
    elif product_availability.status_code == 503:
        for key, value in ids.items():
            is_failed(value['event_id'], value['trace_id'])
        raise Exception('BP responded with HTTP ' + str(product_availability.status_code) + str(product_availability.text))
    else:
        for key, value in ids.items():
            is_failed(value['event_id'], value['trace_id'])
        json_body={"data": {"code": str(product_availability.status_code), "body": str(product_availability.content)}, "process": "InventoryQuantitySyncSKU", "step": "Product availability checks"}
        response = sqs.send_message(
            QueueUrl=os.environ["InventoryQuantitySyncQueue"],
            MessageBody=json.dumps(json_body)
            )
        return 
    dynamodb = boto3.resource('dynamodb').Table("products")
    for product in ids_array:
        try: 
            get_product = boto3.client('dynamodb').get_item(
                TableName='products',
                Key={"bp_product_id": {"N": str(product)}},
                ProjectionExpression='sh_inventoryLevelId, sh_availability, bp_product_id'
            )
            if "Item" not in get_product:
                print ("Product id #%s is missing from the DynamoDB. Filling the table" % (product))
                try:
                    productIDs2BeSynced['products'][product]={
                        "bp_availability": int(product_availability[str(product)]['total']['onHand']), 
                        "event_id": ids[str(product)]['event_id'],
                        "trace_id": ids[str(product)]['trace_id']
                    }
                    dynamodb_item = {
                    "event_id":     ids[str(product)]['event_id'],
                    "lambda":       "InventoryQuantitySyncSKU",
                    "process":      "InventoryQuantitySync",
                    "status":       "Re-try. Triggered ProductsSync2DynamoDB lambda to sync %s product id" % (product),
                    "trace_id":     ids[str(product)]['trace_id'],
                    "timestamp":    int(time.time())
                    }
                    boto3.resource('dynamodb').Table("events").put_item(Item=dynamodb_item)
                except KeyError:
                    pass
            else: 
                print ("Product id #%s is present in the DynamoDB. Updating the table" % (product))
                item = dynamodb.update_item(
                    Key={"bp_product_id": int(product)},
                    UpdateExpression="set bp_availability=:n",
                    ExpressionAttributeValues={
                        ':n': int(product_availability[str(product)]['total']['onHand'])
                    },
                ReturnValues="NONE")
                DynamoDBSearchKeys.append({"bp_product_id": {"N": str(product)}})
        except Exception as e:
            print (e)
            is_failed(ids[product_id]['event_id'], ids[product_id]['trace_id'])
            raise
    if productIDs2BeSynced['products']:
        print ("Invoking Sync Lambda")
        response = sqs.send_message(
            QueueUrl=os.environ["InventoryQuantitySync2DynamoDBQueue"],
            MessageBody=json.dumps(productIDs2BeSynced)
            )
        # updateDB = boto3.client('lambda').invoke(
        #     FunctionName='ProductsSync2DynamoDB',
        #     InvocationType='Event',
        #     LogType='None',
        #     Payload=json.dumps(productIDs2BeSynced)
        # )
    print ("DynamoDBSearchKeys:", DynamoDBSearchKeys)
    if not DynamoDBSearchKeys:
        print ("No products in the DB. Stopping the function to get them processed by ProductsSync2DynamoDB")
        return
    get_products = boto3.client('dynamodb').batch_get_item(
    RequestItems={
        'products': {
            'Keys': DynamoDBSearchKeys,
            'ProjectionExpression': 'sh_inventoryLevelId, sh_availability, bp_product_id, sh_product_id'
            }
        }
    )
    for product_item in get_products['Responses']['products']:
        try:
            print ("Processing %s product id" % (product_item))
            product_id = product_item['bp_product_id']['N']
            availableDelta=int(product_availability[product_id]['total']['onHand'])-int(product_item['sh_availability']['N'])
            query='''mutation {
                                  item: inventoryAdjustQuantity (input: {inventoryLevelId: "%s", availableDelta:%d }) {
                                    inventoryLevel {
                                      available
                                    }
                                    userErrors {
                                      field
                                      message
                                    }
                                  }
                                }''' % (product_item['sh_inventoryLevelId']['S'], availableDelta)
            result['query']=query    
            result['process']="InventoryQuantitySync"
            result['step']="UpdateVariants"
            result['trace_id']=ids[product_id]['trace_id']
            result['bp_product_id']=product_id
            result['sh_product_id']=product_item['sh_product_id']['S']
            response = sqs.send_message(
                    QueueUrl=os.environ["ShopifyGraphQLQueue"],
                    MessageBody=json.dumps(result)
                    )
            dynamodb = boto3.resource('dynamodb').Table("events")
            dynamodb_item = {
            "event_id":     event_id,
            "lambda":       "InventoryQuantitySyncSKU",
            "process":      "InventoryQuantitySync",
            "status":       "Success. Product update query generated",
            "trace_id":     trace_id,
            "timestamp":    int(time.time())
            }
            dynamodb.put_item(Item=dynamodb_item)
        except Exception as e:
            print (e)
            is_failed(ids[product_id]['event_id'], ids[product_id]['trace_id'])
            raise
