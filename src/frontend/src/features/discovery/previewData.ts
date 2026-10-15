// Synthetic preview generated from backend tests/fixtures/us3 using app.sources.discovery.
import type { DiscoveryResult, DiscoveryChanges } from './types'

export const previewData = {
  "previous": {
    "contractVersion": 1,
    "samplingMethod": "head",
    "sampledCount": 3,
    "fields": [
      {
        "path": "customer_code",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "00123",
          "00456",
          "00789"
        ]
      },
      {
        "path": "lines",
        "types": [
          "array"
        ],
        "nullable": false,
        "repeating": true,
        "samples": [
          "[2 items]",
          "[1 items]",
          "[0 items]"
        ]
      },
      {
        "path": "lines[]",
        "types": [
          "object"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "{2 fields}",
          "{1 fields}"
        ]
      },
      {
        "path": "lines[].qty",
        "types": [
          "number"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          2,
          1
        ]
      },
      {
        "path": "lines[].sku",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "SKU-001",
          "SKU-002",
          "SKU-003"
        ]
      },
      {
        "path": "order_date",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "03/04/2026",
          "04/05/2026",
          "2026-10-12"
        ],
        "ambiguity": "date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY"
      },
      {
        "path": "order_no",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "ORD-001",
          "ORD-002",
          "ORD-003"
        ]
      },
      {
        "path": "paid",
        "types": [
          "boolean"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          true,
          false
        ]
      },
      {
        "path": "shipping_address",
        "types": [
          "object"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "{2 fields}",
          "{1 fields}"
        ]
      },
      {
        "path": "shipping_address.city",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "Toronto",
          "Ottawa"
        ]
      },
      {
        "path": "shipping_address.zip",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "M5V"
        ]
      },
      {
        "path": "tags",
        "types": [
          "array"
        ],
        "nullable": false,
        "repeating": true,
        "samples": [
          "[2 items]",
          "[0 items]",
          "[1 items]"
        ]
      },
      {
        "path": "tags[]",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "rush",
          "retail"
        ]
      },
      {
        "path": "total",
        "types": [
          "null",
          "number",
          "string"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          120.5,
          "99.00",
          null
        ]
      }
    ]
  },
  "current": {
    "contractVersion": 1,
    "samplingMethod": "head",
    "sampledCount": 3,
    "fields": [
      {
        "path": "currency",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "CAD"
        ]
      },
      {
        "path": "customer_code",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "00123",
          "00456",
          "00789"
        ]
      },
      {
        "path": "lines",
        "types": [
          "array"
        ],
        "nullable": false,
        "repeating": true,
        "samples": [
          "[2 items]",
          "[1 items]",
          "[0 items]"
        ]
      },
      {
        "path": "lines[]",
        "types": [
          "object"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "{2 fields}",
          "{1 fields}"
        ]
      },
      {
        "path": "lines[].qty",
        "types": [
          "number"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          2,
          1
        ]
      },
      {
        "path": "lines[].sku",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "SKU-001",
          "SKU-002",
          "SKU-003"
        ]
      },
      {
        "path": "order_date",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "03/04/2026",
          "04/05/2026",
          "2026-10-12"
        ],
        "ambiguity": "date_format_ambiguous: DD/MM/YYYY or MM/DD/YYYY"
      },
      {
        "path": "order_no",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "ORD-001",
          "ORD-002",
          "ORD-003"
        ]
      },
      {
        "path": "shipping_address",
        "types": [
          "object"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "{2 fields}",
          "{1 fields}"
        ]
      },
      {
        "path": "shipping_address.city",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "Toronto",
          "Ottawa"
        ]
      },
      {
        "path": "shipping_address.zip",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": false,
        "samples": [
          "M5V"
        ]
      },
      {
        "path": "tags",
        "types": [
          "array"
        ],
        "nullable": false,
        "repeating": true,
        "samples": [
          "[2 items]",
          "[0 items]",
          "[1 items]"
        ]
      },
      {
        "path": "tags[]",
        "types": [
          "string"
        ],
        "nullable": true,
        "repeating": true,
        "samples": [
          "rush",
          "retail"
        ]
      },
      {
        "path": "total",
        "types": [
          "string"
        ],
        "nullable": false,
        "repeating": false,
        "samples": [
          "120.50",
          "99.00",
          "0.00"
        ]
      }
    ]
  },
  "changes": {
    "contractVersion": 1,
    "added": [
      "currency"
    ],
    "missing": [
      "paid"
    ],
    "typeChanges": [
      {
        "path": "total",
        "previousTypes": [
          "null",
          "number",
          "string"
        ],
        "currentTypes": [
          "string"
        ]
      }
    ]
  }
} satisfies { previous: DiscoveryResult; current: DiscoveryResult; changes: DiscoveryChanges }
