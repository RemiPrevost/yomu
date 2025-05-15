import { NextApiRequest, NextApiResponse } from 'next';
import fs from 'fs';
import path from 'path';
import csvParser from 'csv-parser';

type AnswerLog = { id: string; isCorrect: boolean; wrongAnswer?: string; timestamp: string };

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', ['GET']);
    return res.status(405).end(`Method ${req.method} Not Allowed`);
  }

  const filePath = path.join(process.cwd(), 'data', 'extracted_pairs.csv');
  const logsFile = path.join(process.cwd(), 'data', 'answer_logs.json');

  try {
    // Define the log type
    let logs: AnswerLog[] = [];
    if (fs.existsSync(logsFile)) {
      const fileContent = fs.readFileSync(logsFile, 'utf-8');
      logs = JSON.parse(fileContent || '[]');
    }

    // Build a map of word id to whether it has ever been answered correctly
    const correctMap: Record<string, boolean> = {};
    logs.forEach(log => {
      if (log.id && log.isCorrect) {
        correctMap[log.id] = true;
      }
    });

    // Build a set of all ids that have ever been asked
    const askedSet = new Set(logs.map(log => log.id));

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
    res.status(500).json({ error: 'Failed to read the CSV file', details: (error as Error).message });
  }
}
