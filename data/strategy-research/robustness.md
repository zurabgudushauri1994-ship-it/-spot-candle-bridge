# Strategiatutkimus — vaihe 2: kestävyystestit

Samat säännöt ja kulut kuin vaiheessa 1. Kolikkokohtaiset painot vaiheesta 1, salkkutason vol-kohde arvioidaan 60 päivän toteutuneesta volatiliteetista ilman tulevaisuuden tietoa ja rajataan 100 %:n bruttoaltistukseen.

## A. Donchian-ensemble salkkutason volatiliteettikohteella

| Strategia | CAGR % | Sharpe | Max DD % | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe | Julkaisun jälkeen CAGR / Sharpe | 12 kk ikkunoista voitolla % | Huonoin 12 kk % |
|---|---|---|---|---|---|---|---|---|---|
| Donchian-ensemble, ei salkkukohdetta | 10.0 | 1.28 | -10.6 | 8 | 11.9 / 1.50 | 7.9 / 1.04 | 0.2 / 0.06 | 68 | -7.5 |
| Donchian-ensemble, salkku 20 % vol | 36.4 | 1.39 | -37.8 | 27 | 45.4 / 1.65 | 27.4 / 1.12 | -0.5 / 0.09 | 77 | -34.9 |
| Donchian-ensemble, salkku 30 % vol | 44.1 | 1.30 | -45.9 | 38 | 59.4 / 1.59 | 29.6 / 0.98 | -5.9 / -0.06 | 73 | -44.1 |
| Donchian-ensemble, salkku 40 % vol | 48.2 | 1.22 | -54.3 | 46 | 66.3 / 1.50 | 31.2 / 0.92 | -10.1 / -0.14 | 71 | -50.4 |
| Donchian-ensemble, salkku 30 % vol, kulut 0,30 % | 38.0 | 1.16 | -50.1 | 38 | 54.6 / 1.49 | 22.4 / 0.80 | -12.2 / -0.29 | 71 | -48.2 |
| Osta ja pidä (tasapaino) | 44.0 | 0.87 | -80.6 | 87 | 64.7 / 1.03 | 25.0 / 0.67 | -13.6 / 0.11 | 62 | -78.7 |

## B. Yhden kolikon trendi — BTCUSDT

| Strategia | CAGR % | Sharpe | Max DD % | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe | Julkaisun jälkeen CAGR / Sharpe | 12 kk ikkunoista voitolla % | Huonoin 12 kk % |
|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT osta ja pidä | 36.5 | 0.84 | -76.6 | 87 | 23.0 / 0.65 | 52.2 / 1.14 | -0.7 / 0.19 | 65 | -76.2 |
| BTCUSDT SMA 50 | 49.1 | 1.23 | -58.5 | 48 | 46.2 / 1.11 | 52.1 / 1.40 | 16.4 / 0.71 | 78 | -58.3 |
| BTCUSDT SMA 75 | 34.4 | 0.95 | -58.0 | 49 | 25.8 / 0.75 | 44.2 / 1.22 | 17.9 / 0.79 | 71 | -56.6 |
| BTCUSDT SMA 100 | 38.0 | 1.02 | -38.8 | 50 | 38.7 / 0.98 | 37.3 / 1.07 | 10.3 / 0.54 | 76 | -38.8 |
| BTCUSDT SMA 125 | 47.5 | 1.19 | -33.6 | 51 | 50.5 / 1.18 | 44.4 / 1.20 | 10.2 / 0.53 | 79 | -33.6 |
| BTCUSDT SMA 150 | 39.1 | 1.04 | -44.3 | 51 | 37.8 / 0.98 | 40.5 / 1.12 | 9.5 / 0.51 | 68 | -41.9 |
| BTCUSDT SMA 200 | 28.9 | 0.84 | -64.4 | 51 | 20.9 / 0.66 | 37.9 / 1.04 | 15.7 / 0.74 | 63 | -64.4 |
| BTCUSDT SMA 100, kulut 0,30 % | 35.6 | 0.97 | -39.8 | 50 | 36.8 / 0.95 | 34.3 / 1.01 | 8.5 / 0.47 | 73 | -39.8 |
| BTCUSDT EMA 20/100 | 33.7 | 0.93 | -49.7 | 52 | 35.5 / 0.92 | 31.9 / 0.94 | 9.6 / 0.52 | 68 | -47.1 |
| BTCUSDT Donchian-ensemble 25 % vol | 12.6 | 0.96 | -19.5 | 19 | 11.9 / 1.02 | 13.3 / 0.92 | -0.1 / 0.05 | 64 | -16.5 |
| BTCUSDT Donchian-ensemble ilman vol-kohdetta | 25.4 | 0.93 | -46.4 | 37 | 27.0 / 0.93 | 23.8 / 0.95 | 2.2 / 0.22 | 63 | -38.1 |

## B. Yhden kolikon trendi — ETHUSDT

| Strategia | CAGR % | Sharpe | Max DD % | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe | Julkaisun jälkeen CAGR / Sharpe | 12 kk ikkunoista voitolla % | Huonoin 12 kk % |
|---|---|---|---|---|---|---|---|---|---|
| ETHUSDT osta ja pidä | 45.4 | 0.88 | -79.3 | 87 | 73.8 / 1.09 | 20.4 / 0.61 | 20.2 / 0.61 | 66 | -76.7 |
| ETHUSDT SMA 50 | 57.8 | 1.12 | -55.2 | 48 | 68.2 / 1.16 | 47.6 / 1.10 | 80.3 / 1.47 | 82 | -54.8 |
| ETHUSDT SMA 75 | 42.1 | 0.92 | -69.0 | 50 | 62.0 / 1.08 | 23.9 / 0.71 | 33.0 / 0.86 | 67 | -59.3 |
| ETHUSDT SMA 100 | 29.0 | 0.74 | -75.0 | 51 | 30.5 / 0.75 | 27.4 / 0.77 | 42.7 / 1.04 | 61 | -63.5 |
| ETHUSDT SMA 125 | 38.6 | 0.87 | -66.7 | 50 | 46.6 / 0.92 | 30.6 / 0.84 | 31.2 / 0.87 | 69 | -54.8 |
| ETHUSDT SMA 150 | 40.4 | 0.88 | -65.7 | 50 | 51.6 / 0.97 | 29.5 / 0.80 | 16.8 / 0.59 | 72 | -55.0 |
| ETHUSDT SMA 200 | 43.1 | 0.92 | -67.1 | 50 | 63.0 / 1.07 | 24.6 / 0.72 | 13.2 / 0.52 | 72 | -49.3 |
| ETHUSDT SMA 100, kulut 0,30 % | 26.3 | 0.70 | -76.2 | 51 | 28.3 / 0.73 | 24.2 / 0.71 | 40.4 / 1.00 | 59 | -64.8 |
| ETHUSDT EMA 20/100 | 35.9 | 0.83 | -63.0 | 50 | 58.2 / 1.02 | 15.9 / 0.56 | 28.1 / 0.82 | 63 | -51.3 |
| ETHUSDT Donchian-ensemble 25 % vol | 12.1 | 0.96 | -15.3 | 12 | 18.2 / 1.34 | 6.1 / 0.54 | 4.3 / 0.46 | 70 | -13.7 |
| ETHUSDT Donchian-ensemble ilman vol-kohdetta | 34.5 | 0.97 | -40.3 | 33 | 63.6 / 1.31 | 9.4 / 0.46 | 9.5 / 0.47 | 71 | -35.9 |

## C. Yhdistelmä

| Strategia | CAGR % | Sharpe | Max DD % | Altistus % | IS CAGR / Sharpe | OOS CAGR / Sharpe | Julkaisun jälkeen CAGR / Sharpe | 12 kk ikkunoista voitolla % | Huonoin 12 kk % |
|---|---|---|---|---|---|---|---|---|---|
| 50 % Donchian-salkku 30 % vol + 50 % BTC SMA 100 | 43.0 | 1.29 | -37.3 | 44 | 51.2 / 1.42 | 34.8 / 1.14 | 2.6 / 0.22 | 79 | -36.2 |

## Vuosituotot %

| Strategia | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| Donchian-ensemble, ei salkkukohdetta | 0.0 | 26.3 | 30.6 | -4.7 | 14.6 | 19.6 | -3.3 | 0.7 |
| Donchian-ensemble, salkku 20 % vol | 0.0 | 171.9 | 99.3 | -17.4 | 74.2 | 60.6 | -5.4 | -5.2 |
| Donchian-ensemble, salkku 30 % vol | 0.0 | 257.3 | 150.7 | -27.9 | 81.8 | 88.3 | -15.4 | -7.6 |
| Donchian-ensemble, salkku 40 % vol | 0.0 | 324.8 | 200.1 | -40.0 | 95.3 | 107.5 | -24.8 | -8.1 |
| Donchian-ensemble, salkku 30 % vol, kulut 0,30 % | 0.0 | 242.8 | 145.0 | -31.9 | 71.6 | 80.1 | -19.0 | -14.0 |
| Osta ja pidä (tasapaino) | 0.0 | 244.4 | 693.0 | -73.0 | 131.3 | 92.8 | -47.5 | -0.3 |
| BTCUSDT osta ja pidä | 0.0 | 301.1 | 59.8 | -64.2 | 155.6 | 121.3 | -6.3 | -6.9 |
| BTCUSDT SMA 50 | 0.0 | 311.5 | 124.7 | -50.5 | 138.1 | 75.8 | 3.1 | 14.0 |
| BTCUSDT SMA 75 | 0.0 | 171.0 | 66.6 | -44.5 | 103.3 | 52.4 | 9.4 | 18.3 |
| BTCUSDT SMA 100 | 0.0 | 166.1 | 76.5 | -21.1 | 81.5 | 63.5 | 3.8 | 8.0 |
| BTCUSDT SMA 125 | 0.0 | 199.0 | 88.0 | -8.6 | 88.6 | 88.5 | 6.5 | 6.7 |
| BTCUSDT SMA 150 | 0.0 | 186.5 | 35.8 | -7.2 | 91.4 | 93.4 | -10.2 | 9.4 |
| BTCUSDT SMA 200 | 0.0 | 173.3 | -21.7 | 0.0 | 93.8 | 80.8 | -17.7 | 17.5 |
| BTCUSDT SMA 100, kulut 0,30 % | 0.0 | 160.2 | 73.1 | -22.1 | 78.0 | 59.1 | 0.9 | 7.2 |
| BTCUSDT EMA 20/100 | 0.0 | 190.4 | 37.0 | -15.1 | 62.1 | 69.9 | 4.8 | -1.0 |
| BTCUSDT Donchian-ensemble 25 % vol | 0.0 | 55.7 | 12.9 | -10.7 | 27.7 | 33.5 | -6.3 | 0.6 |
| BTCUSDT Donchian-ensemble ilman vol-kohdetta | 0.0 | 154.8 | 36.5 | -25.2 | 47.1 | 65.8 | -8.4 | 0.8 |
| ETHUSDT osta ja pidä | 0.0 | 462.5 | 399.2 | -67.5 | 90.8 | 46.3 | -11.0 | -18.4 |
| ETHUSDT SMA 50 | 0.0 | 279.8 | 205.0 | -30.8 | 54.5 | 21.9 | 87.9 | 23.8 |
| ETHUSDT SMA 75 | 0.0 | 290.0 | 220.8 | -44.9 | 36.1 | 17.9 | 36.0 | 3.2 |
| ETHUSDT SMA 100 | 0.0 | 104.5 | 164.6 | -46.4 | 48.8 | 16.4 | 38.2 | 4.7 |
| ETHUSDT SMA 125 | 0.0 | 119.6 | 258.9 | -41.3 | 67.0 | 22.9 | 30.6 | 2.7 |
| ETHUSDT SMA 150 | 0.0 | 143.8 | 164.7 | -18.1 | 64.0 | 48.8 | 1.6 | 7.4 |
| ETHUSDT SMA 200 | 0.0 | 104.1 | 313.7 | -16.2 | 49.4 | 48.5 | -3.1 | 7.4 |
| ETHUSDT SMA 100, kulut 0,30 % | 0.0 | 101.2 | 157.3 | -47.7 | 44.6 | 13.3 | 35.5 | 2.7 |
| ETHUSDT EMA 20/100 | 0.0 | 173.9 | 259.9 | -36.4 | 25.4 | 2.1 | 31.5 | 4.0 |
| ETHUSDT Donchian-ensemble 25 % vol | 0.0 | 45.6 | 38.8 | -3.4 | 7.5 | 13.6 | 3.5 | -1.1 |
| ETHUSDT Donchian-ensemble ilman vol-kohdetta | 0.0 | 170.6 | 196.4 | -10.7 | 12.7 | 22.2 | 7.4 | -4.8 |
| 50 % Donchian-salkku 30 % vol + 50 % BTC SMA 100 | 0.0 | 215.7 | 117.3 | -23.7 | 83.8 | 78.3 | -5.7 | 0.5 |
