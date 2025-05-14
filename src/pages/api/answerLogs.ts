import { NextApiRequest, NextApiResponse } from 'next';
import fs from 'fs';
import path from 'path';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', ['POST']);
    return res.status(405).end(`Method ${req.method} Not Allowed`);
  }

  const logsDir = path.join(process.cwd(), 'data');
  const logsFile = path.join(logsDir, 'answer_logs.json');

  try {
    // Ensure the data directory exists
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir);
    }

    // Read existing logs or start with an empty array
    let logs = [];
    if (fs.existsSync(logsFile)) {
      const fileContent = fs.readFileSync(logsFile, 'utf-8');
      logs = JSON.parse(fileContent || '[]');
    }

    // Add the new log entry
    logs.push({ ...req.body, timestamp: new Date().toISOString() });

    // Write back to the file
    fs.writeFileSync(logsFile, JSON.stringify(logs, null, 2));

    res.status(200).json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to log the answer' });
  }
}
