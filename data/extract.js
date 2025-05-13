// This script extracts pairs of <h3>.*</h3> and <p>.*</p> from an HTML file
const fs = require('fs');
const path = require('path');

// Path to the HTML file
const filePath = path.join(__dirname, 'extract.html');

// Read the HTML file
fs.readFile(filePath, 'utf8', (err, data) => {
  if (err) {
    console.error('Error reading the file:', err);
    return;
  }

  // Regular expression to match <h3>.*</h3> followed by <p>.*</p>
  const regex = /<h3>(.*?)<\/h3>\s*<p>(.*?)<\/p>/g;

  // Extract matches
  const matches = [];
  let match;
  while ((match = regex.exec(data)) !== null) {
    matches.push({ h3: match[1], p: match[2] });
  }

  // Reverse the order of matches
  const reversedMatches = matches.reverse();

  // Convert reversed matches to CSV format
  const csvHeader = 'id,ja,en\n'; // ISO codes for Japanese and English
  const csvRows = reversedMatches.map(({ h3, p }, index) => `${index},"${h3}","${p}"`).join('\n');
  const csvContent = csvHeader + csvRows;

  // Write the CSV to a file
  const outputFilePath = path.join(__dirname, 'extracted_pairs.csv');
  fs.writeFile(outputFilePath, csvContent, (err) => {
    if (err) {
      console.error('Error writing the output file:', err);
    } else {
      console.log('Extracted pairs saved to:', outputFilePath);
    }
  });
});