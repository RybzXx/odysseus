"""
services/bookings

The reply a website registration gets, and the days Odysseus prices for it.

A registration on bilweekend.com names a published tour. That is a different
thing from a Curated form or a Queue photo, which name no tour at all and which
`services/itinerary` exists to answer. This package holds what is true only of
registrations: which of the two templates the customer receives, and which
Odysseus day codes a website tour is made of.

Nothing here reads a customer's name from a job row. See `templates.render`.
"""
