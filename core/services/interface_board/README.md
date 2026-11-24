# Interface Board

The service controls the Remora POD interface board at `/interface_board/v1.0/`.
API documentation is available at `/interface_board/api-docs`.

The board is discovered by its USB identity. If more than one board matches,
set `INTERFACE_BOARD_PORT` to select a serial device. `INTERFACE_BOARD_BAUD`
and `INTERFACE_BOARD_SLAVE` default to `115200` and `1`. Configure these in
the BlueOS service runtime environment.

An enable or disable request succeeds only after the observed state matches.
A communication error after a write means the channel state may be unknown;
read status before deciding what to do. A 409 response includes the latest
board status when the observed state does not match.
