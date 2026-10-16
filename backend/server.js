const express = require('express');
const app = express();

app.use(express.json());
app.use(express.static('../frontend'));

app.get('/api/test', (req, res) => {
  res.json({ mesaj: 'Sunucu çalışıyor' });
});

app.listen(3000, () => console.log('http://localhost:3000'));