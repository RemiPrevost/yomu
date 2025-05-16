import { NextApiRequest, NextApiResponse } from 'next';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, PutCommand } from '@aws-sdk/lib-dynamodb';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', ['POST']);
    return res.status(405).end(`Method ${req.method} Not Allowed`);
  }

  // DynamoDB config from env
  const client = new DynamoDBClient({
    region: process.env.DYNAMODB_REGION,
    endpoint: process.env.DYNAMODB_ENDPOINT,
    credentials: {
      accessKeyId: process.env.AWS_ACCESS_KEY_ID || '',
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY || '',
    },
  });
  const ddbDocClient = DynamoDBDocumentClient.from(client);
  const tableName = process.env.DYNAMODB_TABLE || 'AnswerLogs';

  try {
    const logItem = { ...req.body, timestamp: new Date().toISOString() };
    await ddbDocClient.send(
      new PutCommand({
        TableName: tableName,
        Item: logItem,
      })
    );
    res.status(200).json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to log the answer', details: (error as Error).message });
  }
}
