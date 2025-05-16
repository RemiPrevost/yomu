import { NextApiRequest, NextApiResponse } from 'next';
import fs from 'fs';
import path from 'path';
import csvParser from 'csv-parser';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, ScanCommand } from '@aws-sdk/lib-dynamodb';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', ['GET']);
    return res.status(405).end(`Method ${req.method} Not Allowed`);
  }

  const filePath = path.join(process.cwd(), 'data', 'extracted_pairs.csv');

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
    // Fetch all logs from DynamoDB
    const logsResult = await ddbDocClient.send(
      new ScanCommand({ TableName: tableName })
    );
    const logs = logsResult.Items || [];

    // Build a map of word id to whether it has ever been answered correctly
    const correctMap: Record<string, boolean> = {};
    logs.forEach((log) => {
      if (typeof log.id === 'string' && log.isCorrect) {
        correctMap[log.id] = true;
      }
    });

    // Build a set of all ids that have ever been asked
    const askedSet = new Set(logs.map((log) => log.id).filter((id): id is string => typeof id === 'string'));

    // Read the CSV and filter
    const filtered: { en: string; id: string; ja: string; }[] = [];
    fs.createReadStream(filePath)
      .pipe(csvParser())
      .on('data', (data) => {
        const neverAsked = !askedSet.has(data.id);
        const neverCorrect = !correctMap[data.id];
        if (neverAsked || neverCorrect) {
          filtered.push({ en: data.en, id: data.id, ja: data.ja });
        }
      })
      .on('end', () => {
        res.status(200).json(filtered.slice(0, 10));
      });
  } catch (error) {
    res.status(500).json({ error: 'Failed to read the logs or CSV file', details: (error as Error).message });
  }
}
