# Interface Board

The service exposes the Remora POD interface board at `/interface-board/v1.0/`
(or directly on port 9113). Its API documentation is at `/interface-board/api-docs`.

`GET /board` reads firmware and channel status. `PUT /channels/{number}` accepts
`{"enabled": true}` or `{"enabled": false}` and returns the confirmed board status.
Channels 1–5 are Camera Back, Camera Mid, Camera Front, PLC, and GNSS.
Faults are reported but not cleared or acted upon. A communication error after a
write means the channel state may be unknown; read status before deciding what to do.

The service automatically selects a matching USB board. Set `INTERFACE_BOARD_PORT`
to a serial device path to override discovery. `INTERFACE_BOARD_BAUD` and
`INTERFACE_BOARD_SLAVE` default to `115200` and `1`. Configure these in the
BlueOS service runtime environment. No channel state is changed at startup,
shutdown, or reconnection.

Like other BlueOS APIs, this service is network-accessible without service-specific
authentication. Anyone with access can switch the PLC and GNSS channels.
