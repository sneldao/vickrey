# Messages API fan-out patch

`iota-messages-api-send_data.py.diff` applies to [eclipse-aerios/iota-messages-api](https://github.com/eclipse-aerios/iota-messages-api) `send_data.py` at commit `1ed089a1812cb15025e3775f9c8b7d43fdf519bb` (Apache-2.0). That file stays in the sibling clone. This repo only stores the patch.

After Hornet accepts a block (HTTP 2xx with `blockId`), the patched upload handler POSTs the application copy to the ledger:

```json
{ "blockId": "...", "tag": "...", "message": {}, "hornetStatus": 201 }
```

`message` is the original JSON object. The bytes written to Hornet are still `json.dumps` of that object, same as upstream. A ledger outage is logged and does not fail the Tangle upload.

`LEDGER_URL` defaults to `http://host.docker.internal:8088/ingest` (ledger port published on the Docker host). When the messages-api container shares a network with this repo's `ledger` service, set `LEDGER_URL=http://ledger:8088/ingest`.

## Apply on the sibling clone

```bash
git clone https://github.com/eclipse-aerios/iota-messages-api.git ../iota-messages-api
cd ../iota-messages-api
git checkout 1ed089a1812cb15025e3775f9c8b7d43fdf519bb
patch -p1 --forward < ../vickrey/patches/iota-messages-api-send_data.py.diff
```

Rebuild and run on the Day 1 network (`iota-net`), with the ledger already publishing port 8088:

```bash
docker build -t iota-messages-api:ledger .
docker rm -f iota-messages-api
docker run -d --name iota-messages-api \
  --network "${HORNET_NETWORK:-iota-net}" \
  -p 5555:5555 \
  -e LEDGER_URL=http://host.docker.internal:8088/ingest \
  --add-host=host.docker.internal:host-gateway \
  iota-messages-api:ledger
```

If the ledger container is attached to `iota-net` (see `docker-compose.iotanet.yml`), use `-e LEDGER_URL=http://ledger:8088/ingest` and drop the `host.docker.internal` mapping. The container name on that network is `ledger`.

Confirm fan-out with an upload, then `curl -sS http://127.0.0.1:8088/messages?tag=...`. The messages-api log prints `ledger fan-out URL` at startup and one `ledger fan-out` line per accepted block.

Upstream image `eclipseaerios/iota-messages-api:1.0.2` does not include this patch. Build from the patched clone.
